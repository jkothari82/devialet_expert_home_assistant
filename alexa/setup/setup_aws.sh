#!/usr/bin/env bash
#
# Provisions the AWS resources needed for the Devialet Alexa integration.
#
# Prerequisites:
#   - AWS CLI v2 installed and configured (aws configure)
#   - jq installed
#
# Usage:
#   chmod +x setup_aws.sh
#   ./setup_aws.sh
#
# After running this script you still need to:
#   1. Create the Alexa Smart Home Skill in the Alexa Developer Console
#   2. Link the Lambda function as the skill endpoint
#   3. Copy certificates to your bridge host
#
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
THING_NAME="${THING_NAME:-devialet-expert}"
POLICY_NAME="${POLICY_NAME:-devialet-expert-iot-policy}"
LAMBDA_NAME="${LAMBDA_NAME:-devialet-alexa-skill}"
ROLE_NAME="${ROLE_NAME:-devialet-alexa-lambda-role}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/../bridge/certs"

echo "=== Devialet Alexa Integration — AWS Setup ==="
echo "Region:     ${REGION}"
echo "Thing:      ${THING_NAME}"
echo "Lambda:     ${LAMBDA_NAME}"
echo ""

# ---------------------------------------------------------------
# 1. IoT Thing
# ---------------------------------------------------------------
echo "--- Creating IoT Thing '${THING_NAME}' ..."
aws iot create-thing \
    --thing-name "${THING_NAME}" \
    --region "${REGION}" 2>/dev/null || echo "    (already exists)"

# ---------------------------------------------------------------
# 2. IoT certificates
# ---------------------------------------------------------------
echo "--- Creating IoT certificates ..."
mkdir -p "${CERT_DIR}"

CERT_RESPONSE=$(aws iot create-keys-and-certificate \
    --set-as-active \
    --certificate-pem-outfile "${CERT_DIR}/certificate.pem" \
    --public-key-outfile      "${CERT_DIR}/public.key" \
    --private-key-outfile     "${CERT_DIR}/private.key" \
    --region "${REGION}")

CERT_ARN=$(echo "${CERT_RESPONSE}" | jq -r '.certificateArn')
echo "    Certificate ARN: ${CERT_ARN}"

# Download Amazon Root CA
echo "--- Downloading Amazon Root CA ..."
curl -s -o "${CERT_DIR}/AmazonRootCA1.pem" \
    "https://www.amazontrust.com/repository/AmazonRootCA1.pem"

# ---------------------------------------------------------------
# 3. IoT policy
# ---------------------------------------------------------------
echo "--- Creating IoT policy '${POLICY_NAME}' ..."
aws iot create-policy \
    --policy-name "${POLICY_NAME}" \
    --policy-document "file://${SCRIPT_DIR}/iot_policy.json" \
    --region "${REGION}" 2>/dev/null || echo "    (already exists)"

echo "--- Attaching policy to certificate ..."
aws iot attach-policy \
    --policy-name "${POLICY_NAME}" \
    --target "${CERT_ARN}" \
    --region "${REGION}"

echo "--- Attaching certificate to thing ..."
aws iot attach-thing-principal \
    --thing-name "${THING_NAME}" \
    --principal "${CERT_ARN}" \
    --region "${REGION}"

# ---------------------------------------------------------------
# 4. Lambda IAM role
# ---------------------------------------------------------------
echo "--- Creating Lambda IAM role '${ROLE_NAME}' ..."
aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${SCRIPT_DIR}/lambda_trust.json" \
    2>/dev/null || echo "    (already exists)"

aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${ROLE_NAME}-policy" \
    --policy-document "file://${SCRIPT_DIR}/lambda_policy.json"

ROLE_ARN=$(aws iam get-role --role-name "${ROLE_NAME}" \
    | jq -r '.Role.Arn')
echo "    Role ARN: ${ROLE_ARN}"

# IAM role propagation can take a few seconds
echo "    Waiting for role propagation ..."
sleep 10

# ---------------------------------------------------------------
# 5. Lambda function
# ---------------------------------------------------------------
echo "--- Packaging Lambda function ..."
LAMBDA_DIR="${SCRIPT_DIR}/../lambda"
LAMBDA_ZIP="/tmp/devialet-alexa-lambda.zip"
(cd "${LAMBDA_DIR}" && zip -j "${LAMBDA_ZIP}" lambda_function.py)

echo "--- Creating Lambda function '${LAMBDA_NAME}' ..."
aws lambda create-function \
    --function-name "${LAMBDA_NAME}" \
    --runtime python3.12 \
    --role "${ROLE_ARN}" \
    --handler lambda_function.lambda_handler \
    --zip-file "fileb://${LAMBDA_ZIP}" \
    --timeout 8 \
    --memory-size 128 \
    --environment "Variables={IOT_THING_NAMES=${THING_NAME}}" \
    --region "${REGION}" 2>/dev/null \
  || {
    echo "    (function exists — updating code) ..."
    aws lambda update-function-code \
        --function-name "${LAMBDA_NAME}" \
        --zip-file "fileb://${LAMBDA_ZIP}" \
        --region "${REGION}"
    aws lambda update-function-configuration \
        --function-name "${LAMBDA_NAME}" \
        --environment "Variables={IOT_THING_NAMES=${THING_NAME}}" \
        --region "${REGION}"
  }

LAMBDA_ARN=$(aws lambda get-function \
    --function-name "${LAMBDA_NAME}" \
    --region "${REGION}" | jq -r '.Configuration.FunctionArn')
echo "    Lambda ARN: ${LAMBDA_ARN}"

# ---------------------------------------------------------------
# 6. Get IoT endpoint
# ---------------------------------------------------------------
IOT_ENDPOINT=$(aws iot describe-endpoint \
    --endpoint-type iot:Data-ATS \
    --region "${REGION}" | jq -r '.endpointAddress')

# ---------------------------------------------------------------
# Done
# ---------------------------------------------------------------
echo ""
echo "=== Setup complete! ==="
echo ""
echo "IoT endpoint:   ${IOT_ENDPOINT}"
echo "Lambda ARN:     ${LAMBDA_ARN}"
echo "Certificates:   ${CERT_DIR}/"
echo ""
echo "Next steps:"
echo "  1. Go to https://developer.amazon.com/alexa/console/ask"
echo "     Create a Smart Home skill and set the Lambda ARN as the endpoint."
echo ""
echo "  2. Add Alexa Smart Home trigger to your Lambda:"
echo "     aws lambda add-permission \\"
echo "       --function-name ${LAMBDA_NAME} \\"
echo "       --statement-id alexa-smart-home \\"
echo "       --action lambda:InvokeFunction \\"
echo "       --principal alexa-connectedhome.amazon.com \\"
echo "       --event-source-token <YOUR_ALEXA_SKILL_ID> \\"
echo "       --region ${REGION}"
echo ""
echo "  3. Copy certs to your bridge host and update config.yaml:"
echo "     - iot.endpoint: ${IOT_ENDPOINT}"
echo "     - iot.thing_name: ${THING_NAME}"
echo ""
echo "  4. Start the bridge:"
echo "     cd alexa/bridge && pip install -r requirements.txt"
echo "     python bridge.py --config config.yaml"
