# Deepgram <-> Twilio live-streaming Python demo

The code sample in this branch shows how to send Aura TTS from Deepgram to an attached Twilio phonecall/stream.

The TwiML Bin you will need for this should look like the following:

```
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman" language="en">"This call may be recorded."</Say>
  <Connect>
    <Stream url="wss://your.server.address/twilio" />
  </Connect>
</Response>
```

Note that the `<Connect>` verb is required for bi-directional communication.

See the following for more info: https://www.twilio.com/docs/voice/twiml/stream#websocket-messages---to-twilio
