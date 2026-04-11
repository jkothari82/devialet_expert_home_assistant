# Alexa Smart Home Skill for Devialet Expert

Control your Devialet Expert amplifier with Alexa voice commands — no Home
Assistant required.

## Architecture

```
┌───────────┐      ┌────────┐      ┌──────────────┐      ┌─────────┐      ┌──────────┐
│   Alexa   │ ───> │ Lambda │ ───> │  IoT Shadow  │ <──> │  Bridge │ ───> │ Devialet │
│  (cloud)  │ <─── │ (AWS)  │ <─── │  (AWS IoT)   │      │ (local) │ <─── │  Expert  │
└───────────┘      └────────┘      └──────────────┘      └─────────┘      └──────────┘
                                        MQTT                  UDP
```

| Component | Where it runs | What it does |
|-----------|---------------|--------------|
| **Lambda** | AWS (us-east-1) | Handles Alexa directives, reads/writes IoT Shadow |
| **IoT Shadow** | AWS IoT Core | Stores device state; brokers commands between cloud and LAN |
| **Bridge** | Your LAN (RPi, NAS, etc.) | Discovers Devialet via UDP, syncs state with IoT Shadow |

## Supported Voice Commands

| Command | Alexa Interface |
|---------|-----------------|
| "Alexa, turn on the Devialet" | PowerController |
| "Alexa, turn off the Devialet" | PowerController |
| "Alexa, set Devialet volume to 40" | Speaker.SetVolume |
| "Alexa, turn up the volume on Devialet" | Speaker.AdjustVolume |
| "Alexa, mute the Devialet" | Speaker.SetMute |
| "Alexa, unmute the Devialet" | Speaker.SetMute |
| "Alexa, switch Devialet input to Optical 1" | InputController |
| "Alexa, is the Devialet on?" | ReportState |

Volume is mapped from Alexa 0-100 to the Devialet's safe range (max -10 dB).

## Prerequisites

- **AWS account** with CLI v2 configured (`aws configure`)
- **Amazon Developer account** (same email as your Alexa account)
- **Python 3.10+** on the bridge host
- **Devialet Expert** on the same LAN as the bridge host
- **jq** installed (for the setup script)

## Setup

### 1. Provision AWS Resources

```bash
cd alexa/setup
chmod +x setup_aws.sh
./setup_aws.sh
```

This creates:
- IoT Thing + certificates
- IoT policy (shadow access)
- Lambda function with IAM role
- Saves certificates to `alexa/bridge/certs/`

Note the **Lambda ARN** and **IoT endpoint** printed at the end.

### 2. Create the Alexa Smart Home Skill

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask)
2. **Create Skill** -> name it "Devialet" -> choose **Smart Home** -> **Provision your own**
3. Under **Smart Home** -> **Your Skill ID** -> copy the skill ID (starts with `amzn1.ask.skill.`)
4. Under **Smart Home** -> set **Default endpoint** to your Lambda ARN
5. Add the Alexa trigger to your Lambda (replace `<SKILL_ID>`):

```bash
aws lambda add-permission \
  --function-name devialet-alexa-skill \
  --statement-id alexa-smart-home \
  --action lambda:InvokeFunction \
  --principal alexa-connectedhome.amazon.com \
  --event-source-token <SKILL_ID> \
  --region us-east-1
```

### 3. Configure and Start the Bridge

On your bridge host (same LAN as the Devialet):

```bash
cd alexa/bridge
pip install -r requirements.txt

# Copy config and fill in your values
cp config.example.yaml config.yaml
# Edit config.yaml with your IoT endpoint, thing name, and cert paths

# Test
python bridge.py --config config.yaml --log-level DEBUG
```

You should see:
```
Connected to AWS IoT Core
Subscribed to shadow delta
Bridge running — listening for Devialet devices on LAN
Tracking Devialet 'Living Room' at 192.168.1.x
Shadow reported state updated
```

### 4. Discover Devices in Alexa

1. Open the Alexa app on your phone
2. Go to **Devices** -> **+** -> **Add Device** -> **Other**
3. Tap **Discover Devices**
4. Your Devialet should appear as a speaker

### 5. (Optional) Run Bridge as a Service

Copy the systemd unit file and enable it:

```bash
sudo cp alexa/setup/devialet-bridge.service /etc/systemd/system/
# Edit the service file to match your paths and user
sudo systemctl daemon-reload
sudo systemctl enable devialet-bridge
sudo systemctl start devialet-bridge
sudo journalctl -u devialet-bridge -f
```

## Region Notes

Deploy the Lambda in the region matching your Alexa account:

| Alexa Region | Lambda Region |
|--------------|---------------|
| North America | us-east-1 |
| Europe | eu-west-1 |
| Far East | us-west-2 |

Set `AWS_REGION` before running `setup_aws.sh` if you're not in North America:
```bash
AWS_REGION=eu-west-1 ./setup_aws.sh
```

## Troubleshooting

**Bridge can't find Devialet**
- The Devialet must be on the same VLAN/subnet as the bridge
- Check that UDP port 45454 is not blocked by a firewall
- Try running `python devialet_expert.py` from the repo root as a standalone test

**Alexa says "Device is not responding"**
- Check that the bridge is running and connected: `journalctl -u devialet-bridge`
- Verify the IoT shadow has data: `aws iot-data get-thing-shadow --thing-name devialet-expert /dev/stdout`
- Check Lambda logs: CloudWatch -> Log groups -> `/aws/lambda/devialet-alexa-skill`

**Volume seems too quiet at 100%**
- By design: Alexa 100% = Devialet -10 dB (safe maximum). The Devialet can go up to +30 dB but that risks speaker damage. Adjust `MAX_VOLUME_INT` in both `lambda_function.py` and `bridge.py` if you need more headroom.

## File Structure

```
alexa/
├── README.md                       # This file
├── lambda/
│   ├── lambda_function.py          # Alexa Smart Home Skill handler
│   └── requirements.txt
├── bridge/
│   ├── bridge.py                   # Local LAN <-> IoT bridge
│   ├── config.example.yaml         # Bridge configuration template
│   └── requirements.txt
└── setup/
    ├── setup_aws.sh                # AWS resource provisioning script
    ├── iot_policy.json             # IoT Thing policy
    ├── lambda_policy.json          # Lambda IAM policy
    ├── lambda_trust.json           # Lambda trust policy
    └── devialet-bridge.service     # systemd unit file
```
