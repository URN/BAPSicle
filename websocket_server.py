import asyncio
import multiprocessing
import queue
from typing import List
import websockets
import json

baps_clients = set()
channel_to_q = None
webstudio_to_q: List[multiprocessing.Queue]
server_name = None



async def websocket_handler(websocket, path):
    baps_clients.add(websocket)
    await websocket.send(json.dumps({"message": "Hello", "serverName": server_name}))
    print("New Client: {}".format(websocket))
    for channel in channel_to_q:
        channel.put("STATUS")

    async def handle_from_webstudio():
        try:
            async for message in websocket:
                data = json.loads(message)
                channel = int(data["channel"])
                if "command" in data.keys():
                    if data["command"] == "PLAY":
                        channel_to_q[channel].put("PLAY")
                    elif data["command"] == "PAUSE":
                        channel_to_q[channel].put("PAUSE")
                    elif data["command"] == "UNPAUSE":
                        channel_to_q[channel].put("UNPAUSE")
                    elif data["command"] == "STOP":
                        channel_to_q[channel].put("STOP")
                    elif data["command"] == "SEEK":
                        channel_to_q[channel].put("SEEK:" + str(data["time"]))
                    elif data["command"] == "LOAD":
                        channel_to_q[channel].put("LOAD:" + str(data["weight"]))
                    elif data["command"] == "ADD":
                        print(data)
                        if "managedId" in data["newItem"].keys() and isinstance(data["newItem"]["managedId"], str):
                            if data["newItem"]["managedId"].startswith("managed"):
                                managed_id = int(data["newItem"]["managedId"].split(":")[1])
                            else:
                                managed_id = int(data["newItem"]["managedId"])
                        else:
                            managed_id = None
                        new_item: Dict[str, any] = {
                            "channelWeight": int(data["newItem"]["weight"]),
                            "filename": None,
                            "title":  data["newItem"]["title"],
                            "artist":  data["newItem"]["artist"] if "artist" in data["newItem"].keys() else None,
                            "timeslotItemId": int(data["newItem"]["timeslotItemId"]) if "timeslotItemId" in data["newItem"].keys() and data["newItem"]["timeslotItemId"] != None else None,
                            "trackId": int(data["newItem"]["trackId"]) if "trackId" in data["newItem"].keys() and data["newItem"]["trackId"] != None else None,
                            "recordId": int(data["newItem"]["trackId"]) if "trackId" in data["newItem"].keys() and data["newItem"]["trackId"] != None else None,
                            "managedId": managed_id
                        }
                        channel_to_q[channel].put("ADD:" + json.dumps(new_item))
                    elif data["command"] == "REMOVE":
                        channel_to_q[channel].put("REMOVE:" + str(data["weight"]))

                await asyncio.wait([conn.send(message) for conn in baps_clients])

        except websockets.exceptions.ConnectionClosedError as e:
            print("RIP {}, {}".format(websocket, e))

        except Exception as e:
            print("Exception", e)

        finally:
            baps_clients.remove(websocket)

    async def handle_to_webstudio():
        while True:
            for channel in range(len(webstudio_to_q)):
                try:
                    message = webstudio_to_q[channel].get_nowait()
                    if not message.startswith("STATUS"):
                        continue # Ignore non state updates for now.
                    try:
                        message = message.split("OKAY:")[1]
                        message = json.loads(message)
                    except:
                        pass
                    data = json.dumps({
                        "command": "STATUS",
                        "data": message,
                        "channel": channel
                    })
                    await asyncio.wait([conn.send(data) for conn in baps_clients])
                except queue.Empty:
                    pass
            await asyncio.sleep(0.01)

    from_webstudio = asyncio.create_task(handle_from_webstudio())
    to_webstudio = asyncio.create_task(handle_to_webstudio())

    try:
        await asyncio.gather(from_webstudio, to_webstudio)
    finally:
        from_webstudio.cancel()
        to_webstudio.cancel()


class WebsocketServer:

    def __init__(self, in_q, out_q, state):
        global channel_to_q
        global webstudio_to_q
        channel_to_q = in_q
        webstudio_to_q = out_q

        global server_name
        server_name = state.state["server_name"]

        websocket_server = websockets.serve(websocket_handler, state.state["host"], state.state["ws_port"])

        asyncio.get_event_loop().run_until_complete(websocket_server)
        asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    print("Don't do this")
