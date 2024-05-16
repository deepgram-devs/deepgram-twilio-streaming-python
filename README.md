# Deepgram <-> Twilio live-streaming Aura TTS Python demo

To stream audio from Deepgram Aura Text-to-Speech (TTS) into an ongoing Twilio phonecall requires the use of the Twilio streaming API:

https://www.twilio.com/docs/voice/twiml/stream

(note that Deepgram Aura TTS is not available via the Twilio `<Say>` verbs)

For a guide on streaming Twilio phonecall audio to Deepgram for Speech-to-Text (STT) see the following:

https://deepgram.com/learn/deepgram-twilio-streaming


## Pre-requisites

You will need:
* A [Twilio account](https://www.twilio.com/try-twilio) with a Twilio number (the free tier will work).
* A Deepgram API Key - [get an API Key here](https://console.deepgram.com/signup?jump=keys).
* (_Optional_) [ngrok](https://ngrok.com/) to let Twilio access a local server.

You will also need to set up a TwiML Bin like the following in your Twilio Console:
```
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="en">"This call may be monitored or recorded."</Say>
    <Connect>
        <Stream url="wss://a127-75-172-116-97.ngrok-free.app/twilio" />
    </Connect>
</Response>
```
Where you should replace the url with wherever you decide to deploy the server we are about to write (in the case of the above
TwiML Bin, I used ngrok to expose the server running locally, this is the recommended way for quick
development). This TwiML Bin must then be attached to one of your Twilio phone numbers so that it gets
executed whenever someone calls that number.

Note that the `<Connect>` verb is required for bi-directional communication, i.e. in order to send audio (from Aura) to Twilio,
we must use this verb.

## Running the Server

If your TwiML Bin is setup correctly, you should be able to just run the server with:
```
python twilio.py
```
and then start making calls to the phone number the TwiML Bin is attached to! Without further modifications, you
should hear Deepgram Aura say simply: "Hello, how are you today?"

## Code Tour

Let's dive into the code. First we have some import statements:
```
import asyncio
import base64
import json
import sys
import websockets
import ssl
import requests
```

We are using `asyncio` and `websockets` to build an asynchronous websocket server, we will use base64 to handle
encoding audio from Aura to go to Twilio, we will use `json` to deal with parsing
text messages from Twilio and we will use `requests` to make HTTP requests to Deepgram's Aura/TTS endpoint.

Next we have:
```
async def twilio_handler(twilio_ws):
    audio_queue = asyncio.Queue()
    streamsid_queue = asyncio.Queue()
```
we will be spinning up asynchronous tasks for receiving messages from, and sending messages to, Twilio,
and we will use this `streamsid_queue` to pass the stream sid from the `twilio_receiver` task to the
`twilio_sender` task. We do this because to send audio from Deepgram Aura to the correct phonecall,
we must specify this stream sid.

The `twilio_receiver` task is defined next:
```
    async def twilio_receiver(twilio_ws):
        async for message in twilio_ws:
            try:
                data = json.loads(message)

                if data['event'] == 'start':
                    streamsid_queue.put_nowait(data['start']['streamSid'])
            except:
                break
```
This task simply loops over incoming websocket messages from Twilio and extracts the stream sid when it gets it.

Next we have the `twilio_sender` task:
```
    async def twilio_sender(twilio_ws):
        print('twilio_sender started')

        # wait to receive the streamsid for this connection from one of Twilio's messages
        streamsid = await streamsid_queue.get()
```
we first wait to receive the stream sid, and then:
```
        # make a Deepgram Aura TTS request specifying that we want raw mulaw audio as the output
        url = 'https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000&container=none'
        headers = {
            'Authorization': 'Token INSERT_YOUR_DEEPGRAM_API_KEY',
            'Content-Type': 'application/json'
        }
        payload = {
            'text': 'Hello, how are you today?'
        }
        tts_response = requests.post(url, headers=headers, json=payload)
```
we make a request to Deepgram Aura TTS to say "Hello, how are you today?" specifying an audio format of raw, 8000 Hz, mulaw.
(Don't forget to insert your Deepgram API Key here! Or feel free to use environment variables or other more secure means
of including it.)

Next we have:
```
        if tts_response.status_code == 200:
            raw_mulaw = tts_response.content

            # construct a Twilio media message with the raw mulaw (see https://www.twilio.com/docs/voice/twiml/stream#websocket-messages---to-twilio)
            media_message = {
                'event': 'media',
                'streamSid': streamsid,
                'media': {
                    'payload': base64.b64encode(raw_mulaw).decode('ascii')
                }
            }

            # send the TTS audio to the attached phonecall
            await twilio_ws.send(json.dumps(media_message))
```
here we package up the Deepgram Aura TTS audio in the format Twilio expects, including specifying the stream sid, and shoot
that audio back to Twilio via the websocket connection. This is where the magic happens! And the key ingredient is explained
in more detail in the following Twilio docs:

https://www.twilio.com/docs/voice/twiml/stream#websocket-messages---to-twilio

To close out our websocket handler, we run these two asynchronous tasks with `asyncio`:
```
    await asyncio.wait([
        asyncio.ensure_future(twilio_receiver(twilio_ws)),
        asyncio.ensure_future(twilio_sender(twilio_ws))
    ])

    await twilio_ws.close()
```
Finally, for some scaffolding to spin up the server and pointing requests to get handled by the above function, we have:
```
async def router(websocket, path):
    if path == '/twilio':
        print('twilio connection incoming')
        await twilio_handler(websocket)

def main():
    # use this if using ssl
#	ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
#	ssl_context.load_cert_chain('cert.pem', 'key.pem')
#	server = websockets.serve(router, '0.0.0.0', 443, ssl=ssl_context)

    # use this if not using ssl
    server = websockets.serve(router, 'localhost', 5000)

    asyncio.get_event_loop().run_until_complete(server)
    asyncio.get_event_loop().run_forever()

if __name__ == '__main__':
    sys.exit(main() or 0)
```
