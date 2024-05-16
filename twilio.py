import asyncio
import base64
import json
import sys
import websockets
import ssl
import requests


async def twilio_handler(twilio_ws):
    streamsid_queue = asyncio.Queue()

    async def twilio_receiver(twilio_ws):
        async for message in twilio_ws:
            try:
                data = json.loads(message)

                if data["event"] == "start":
                    streamsid_queue.put_nowait(data["start"]["streamSid"])
            except:
                break

    async def twilio_sender(twilio_ws):
        print("twilio_sender started")

        # wait to receive the streamsid for this connection from one of Twilio's messages
        streamsid = await streamsid_queue.get()

        # make a Deepgram Aura TTS request specifying that we want raw mulaw audio as the output
        url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000&container=none"
        headers = {
            "Authorization": "Token INSERT_YOUR_DEEPGRAM_API_KEY",
            "Content-Type": "application/json",
        }
        payload = {"text": "Hello, how are you today?"}
        tts_response = requests.post(url, headers=headers, json=payload)

        if tts_response.status_code == 200:
            raw_mulaw = tts_response.content

            # construct a Twilio media message with the raw mulaw (see https://www.twilio.com/docs/voice/twiml/stream#websocket-messages---to-twilio)
            media_message = {
                "event": "media",
                "streamSid": streamsid,
                "media": {"payload": base64.b64encode(raw_mulaw).decode("ascii")},
            }

            # send the TTS audio to the attached phonecall
            await twilio_ws.send(json.dumps(media_message))

    await asyncio.wait(
        [
            asyncio.ensure_future(twilio_receiver(twilio_ws)),
            asyncio.ensure_future(twilio_sender(twilio_ws)),
        ]
    )

    await twilio_ws.close()


async def router(websocket, path):
    if path == "/twilio":
        print("twilio connection incoming")
        await twilio_handler(websocket)


def main():
    # use this if using ssl
    # 	ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # 	ssl_context.load_cert_chain('cert.pem', 'key.pem')
    # 	server = websockets.serve(router, '0.0.0.0', 443, ssl=ssl_context)

    # use this if not using ssl
    server = websockets.serve(router, "localhost", 5000)

    asyncio.get_event_loop().run_until_complete(server)
    asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    sys.exit(main() or 0)
