import asyncio
import base64
import json
import sys
import websockets
import ssl
from pydub import AudioSegment

subscribers = {}

def deepgram_connect():
	extra_headers = {
		'Authorization': 'Token INSERT_YOUR_API_KEY'
	}
	deepgram_ws = websockets.connect('wss://api.deepgram.com/v1/listen?encoding=mulaw&sample_rate=8000&channels=2&multichannel=true', extra_headers = extra_headers)

	return deepgram_ws

async def twilio_handler(twilio_ws):
	audio_queue = asyncio.Queue()
	callsid_queue = asyncio.Queue()

	async with deepgram_connect() as deepgram_ws:

		async def deepgram_sender(deepgram_ws):
			print('deepgram_sender started')
			while True:
				chunk = await audio_queue.get()
				await deepgram_ws.send(chunk)

		async def deepgram_receiver(deepgram_ws):
			print('deepgram_receiver started')
			# we will wait until the twilio ws connection figures out the callsid
			# then we will initialize our subscribers list for this callsid
			callsid = await callsid_queue.get()
			subscribers[callsid] = []
			# for each deepgram result received, forward it on to all
			# queues subscribed to the twilio callsid
			async for message in deepgram_ws:
				for client in subscribers[callsid]:
					client.put_nowait(message)

			# once the twilio call is over, tell all subscribed clients to close
			# and remove the subscriber list for this callsid
			for client in subscribers[callsid]:
				client.put_nowait('close')

			del subscribers[callsid]

		async def twilio_receiver(twilio_ws):
			print('twilio_receiver started')
			# twilio sends audio data as 160 byte messages containing 20ms of audio each
			# we will buffer 20 twilio messages corresponding to 0.4 seconds of audio to improve throughput performance
			BUFFER_SIZE = 20 * 160
			# the algorithm to deal with mixing the two channels is somewhat complex
			# here we implement an algorithm which fills in silence for channels if that channel is either
			#   A) not currently streaming (e.g. the outbound channel when the inbound channel starts ringing it)
			#   B) packets are dropped (this happens, and sometimes the timestamps which come back for subsequent packets are not aligned)
			inbuffer = bytearray(b'')
			outbuffer = bytearray(b'')
			inbound_chunks_started = False
			outbound_chunks_started = False
			latest_inbound_timestamp = 0
			latest_outbound_timestamp = 0
			async for message in twilio_ws:
				try:
					data = json.loads(message)
					if data['event'] == 'start':
						start = data['start']
						callsid = start['callSid']
						callsid_queue.put_nowait(callsid)
					if data['event'] == 'connected':
						continue
					if data['event'] == 'media':
						media = data['media']
						chunk = base64.b64decode(media['payload'])
						if media['track'] == 'inbound':
							# fills in silence if there have been dropped packets
							if inbound_chunks_started:
								if latest_inbound_timestamp + 20 < int(media['timestamp']):
									bytes_to_fill = 8 * (int(media['timestamp']) - (latest_inbound_timestamp + 20))
									# NOTE: 0xff is silence for mulaw audio
									# and there are 8 bytes per ms of data for our format (8 bit, 8000 Hz)
									inbuffer.extend(b'\xff' * bytes_to_fill)
							else:
								# make it known that inbound chunks have started arriving
								inbound_chunks_started = True
								latest_inbound_timestamp = int(media['timestamp'])
								# this basically sets the starting point for outbound timestamps
								latest_outbound_timestamp = int(media['timestamp']) - 20
							latest_inbound_timestamp = int(media['timestamp'])
							# extend the inbound audio buffer with data
							inbuffer.extend(chunk)
						if media['track'] == 'outbound':
							# make it known that outbound chunks have started arriving
							outbound_chunked_started = True
							# fills in silence if there have been dropped packets
							if latest_outbound_timestamp + 20 < int(media['timestamp']):
								bytes_to_fill = 8 * (int(media['timestamp']) - (latest_outbound_timestamp + 20))
								# NOTE: 0xff is silence for mulaw audio
								# and there are 8 bytes per ms of data for our format (8 bit, 8000 Hz)
								outbuffer.extend(b'\xff' * bytes_to_fill)
							latest_outbound_timestamp = int(media['timestamp'])
							# extend the outbound audio buffer with data
							outbuffer.extend(chunk)
					if data['event'] == 'stop':
						break

					# check if our buffer is ready to send to our audio_queue (and, thus, then to deepgram)
					while len(inbuffer) >= BUFFER_SIZE and len(outbuffer) >= BUFFER_SIZE:
						asinbound = AudioSegment(inbuffer[:BUFFER_SIZE], sample_width=1, frame_rate=8000, channels=1)
						asoutbound = AudioSegment(outbuffer[:BUFFER_SIZE], sample_width=1, frame_rate=8000, channels=1)
						mixed = AudioSegment.from_mono_audiosegments(asinbound, asoutbound)

						# sending to deepgram via the audio_queue
						audio_queue.put_nowait(mixed.raw_data)

						# clearing buffers
						inbuffer = inbuffer[BUFFER_SIZE:]
						outbuffer = outbuffer[BUFFER_SIZE:]
				except:
					break

			# the async for loop will end if the ws connection from twilio dies
			# and if this happens, we should forward an empty byte to deepgram
			# to signal deepgram to send back remaining messages before closing
			audio_queue.put_nowait(b'')

		await asyncio.wait([
			asyncio.ensure_future(deepgram_sender(deepgram_ws)),
			asyncio.ensure_future(deepgram_receiver(deepgram_ws)),
			asyncio.ensure_future(twilio_receiver(twilio_ws))
		])

		await twilio_ws.close()

async def client_handler(client_ws):
	client_queue = asyncio.Queue()

	# first tell the client all active calls
	await client_ws.send(json.dumps(list(subscribers.keys())))

	# then recieve from the client which call they would like to subscribe to
	# and add our client's queue to the subscriber list for that call
	try:
		# you may want to parse a proper json input here
		# instead of grabbing the entire message as the callsid verbatim
		callsid = await client_ws.recv()
		callsid = callsid.strip()
		if callsid in subscribers:
			subscribers[callsid].append(client_queue)
		else:
			await client_ws.close()
	except:
		await client_ws.close()

	async def client_sender(client_ws):
		while True:
			message = await client_queue.get()
			if message == 'close':
				break
			try:
				await client_ws.send(message)
			except:
				# if there was an error, remove this client queue
				subscribers[callsid].remove(client_queue)
				break

	await asyncio.wait([
		asyncio.ensure_future(client_sender(client_ws)),
	])

	await client_ws.close()

async def router(websocket, path):
	if path == '/client':
		print('client connection incoming')
		await client_handler(websocket)
	elif path == '/twilio':
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
