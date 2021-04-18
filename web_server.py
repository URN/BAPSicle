from sanic import Sanic
from sanic.exceptions import NotFound, abort
from sanic.response import html, text, file, redirect
from sanic.response import json as resp_json
from sanic_cors import CORS

from jinja2 import Environment, FileSystemLoader
from urllib.parse import unquote
# , render_template, send_from_directory, request, jsonify, abort
#from flask_cors import CORS
from setproctitle import setproctitle
import logging
from typing import Any, Optional, List
from multiprocessing.queues import Queue
from queue import Empty
from time import sleep
import json
import os

from helpers.os_environment import isBundelled, isMacOS
from helpers.logging_manager import LoggingManager
from helpers.device_manager import DeviceManager
from helpers.state_manager import StateManager
from helpers.the_terminator import Terminator

env = Environment(loader=FileSystemLoader('%s/ui-templates/' % os.path.dirname(__file__)))
app = Sanic("BAPSicle Web Server")


def render_template(file, data, status=200):
    template = env.get_template(file)
    html_content = template.render(data=data)
    return html(html_content, status=status)


logger: LoggingManager
server_state: StateManager

api_from_q: Queue
api_to_q: Queue

player_to_q: List[Queue] = []
player_from_q: List[Queue] = []

# General UI Endpoints


@app.exception(NotFound)
def page_not_found(request, e: Any):
    data = {"ui_page": "404", "ui_title": "404"}
    return render_template("404.html", data=data, status=404)


@app.route("/")
def ui_index(request):
    data = {
        "ui_page": "index",
        "ui_title": "",
        "server_version": server_state.state["server_version"],
        "server_build": server_state.state["server_build"],
        "server_name": server_state.state["server_name"],
    }
    return render_template("index.html", data=data)


@app.route("/status")
def ui_status(request):
    channel_states = []
    for i in range(server_state.state["num_channels"]):
        channel_states.append(status(i))

    data = {"channels": channel_states,
            "ui_page": "status", "ui_title": "Status"}
    return render_template("status.html", data=data)


@app.route("/config/player")
def ui_config_player(request):
    channel_states = []
    for i in range(server_state.state["num_channels"]):
        channel_states.append(status(i))

    outputs = DeviceManager.getAudioOutputs()

    data = {
        "channels": channel_states,
        "outputs": outputs,
        "ui_page": "config",
        "ui_title": "Player Config",
    }
    return render_template("config_player.html", data=data)


@app.route("/config/server")
def ui_config_server(request):
    data = {
        "ui_page": "server",
        "ui_title": "Server Config",
        "state": server_state.state,
        "ser_ports": DeviceManager.getSerialPorts(),
    }
    return render_template("config_server.html", data=data)


@app.route("/config/server/update", methods=["POST"])
def ui_config_server_update(request):
    server_state.update("server_name", request.form["name"])
    server_state.update("host", request.form["host"])
    server_state.update("port", int(request.form["port"]))
    server_state.update("num_channels", int(request.form["channels"]))
    server_state.update("ws_port", int(request.form["ws_port"]))
    server_state.update("serial_port", request.form["serial_port"])

    # Because we're not showing the api key once it's set.
    if "myradio_api_key" in request.form and request.form["myradio_api_key"] != "":
        server_state.update("myradio_api_key", request.form["myradio_api_key"])

    server_state.update("myradio_base_url", request.form["myradio_base_url"])
    server_state.update("myradio_api_url", request.form["myradio_api_url"])
    # stopServer()
    return ui_config_server(request)


@app.route("/logs")
def ui_logs_list(request):
    data = {
        "ui_page": "logs",
        "ui_title": "Logs",
        "logs": ["BAPSicleServer"]
        + ["Player{}".format(x) for x in range(server_state.state["num_channels"])],
    }
    return render_template("loglist.html", data=data)


@app.route("/logs/<path:path>")
def ui_logs_render(request, path):
    log_file = open("logs/{}.log".format(path))
    data = {
        "logs": log_file.read().splitlines(),
        "ui_page": "logs",
        "ui_title": "Logs - {}".format(path),
    }
    log_file.close()
    return render_template("log.html", data=data)


# Player Audio Control Endpoints
# Just useful for messing arround without presenter / websockets.


@app.route("/player/<channel:int>/<command>")
def player_simple(request, channel: int, command: str):

    simple_endpoints = ["play", "pause", "unpause", "stop", "unload", "clear"]
    if command in simple_endpoints:
        player_to_q[channel].put("UI:" + command.upper())
        return redirect("/status")

    abort(404)


@app.route("/player/<channel:int>/seek/<pos:float>")
def player_seek(request, channel: int, pos: float):

    player_to_q[channel].put("UI:SEEK:" + str(pos))

    return redirect("/status")


@app.route("/player/<channel:int>/load/<channel_weight:int>")
def player_load(request, channel: int, channel_weight: int):

    player_to_q[channel].put("UI:LOAD:" + str(channel_weight))
    return redirect("/status")


@app.route("/player/<channel:int>/remove/<channel_weight:int>")
def player_remove(request, channel: int, channel_weight: int):
    player_to_q[channel].put("UI:REMOVE:" + str(channel_weight))

    return redirect("/status")


@app.route("/player/<channel:int>/output/<name:string>")
def player_output(request, channel: int, name: Optional[str]):
    player_to_q[channel].put("UI:OUTPUT:" + unquote(str(name)))
    return redirect("/config/player")


@app.route("/player/<channel:int>/autoadvance/<state:int>")
def player_autoadvance(request, channel: int, state: int):
    player_to_q[channel].put("UI:AUTOADVANCE:" + str(state))
    return redirect("/status")


@app.route("/player/<channel:int>/repeat/<state:string>")
def player_repeat(request, channel: int, state: str):
    player_to_q[channel].put("UI:REPEAT:" + state.upper())
    return redirect("/status")


@app.route("/player/<channel:int>/playonload/<state:int>")
def player_playonload(request, channel: int, state: int):
    player_to_q[channel].put("UI:PLAYONLOAD:" + str(state))
    return redirect("/status")


@app.route("/player/<channel:int>/status")
def player_status_json(request, channel: int):

    return resp_json(status(channel))


@app.route("/player/all/stop")
def player_all_stop(request):

    for channel in player_to_q:
        channel.put("UI:STOP")
    return redirect("/status")


# Show Plan Functions

@app.route("/plan/load/<int:timeslotid>")
def plan_load(request, timeslotid: int):

    for channel in player_to_q:
        channel.put("UI:GET_PLAN:" + str(timeslotid))

    return redirect("/status")


@app.route("/plan/clear")
def plan_clear(request):
    for channel in player_to_q:
        channel.put("UI:CLEAR")
    return redirect("/status")


# API Proxy Endpoints

@app.route("/plan/list")
def api_list_showplans(request):

    while not api_from_q.empty():
        api_from_q.get()  # Just waste any previous status responses.

    api_to_q.put("LIST_PLANS")

    while True:
        try:
            response = api_from_q.get_nowait()
            if response.startswith("LIST_PLANS:"):
                response = response[response.index(":") + 1:]
                return text(response)

        except Empty:
            pass

        sleep(0.02)


@app.route("/library/search/<type>")
def api_search_library(request, type: str):

    if type not in ["managed", "track"]:
        abort(404)

    while not api_from_q.empty():
        api_from_q.get()  # Just waste any previous status responses.

    params = json.dumps(
        {"title": request.args.get("title"), "artist": request.args.get("artist")}
    )
    command = "SEARCH_TRACK:{}".format(params)
    api_to_q.put(command)

    while True:
        try:
            response = api_from_q.get_nowait()
            if response.startswith("SEARCH_TRACK:"):
                response = response[len(command)+1:]
                return text(response)

        except Empty:
            pass

        sleep(0.02)


@app.route("/library/playlists/<type:string>")
def api_get_playlists(request, type: str):

    if type not in ["music", "aux"]:
        abort(401)

    while not api_from_q.empty():
        api_from_q.get()  # Just waste any previous status responses.

    command = "LIST_PLAYLIST_{}".format(type.upper())
    api_to_q.put(command)

    while True:
        try:
            response = api_from_q.get_nowait()
            if response.startswith(command):
                response = response.split(":", 1)[1]
                return text(response)

        except Empty:
            pass

        sleep(0.02)


@app.route("/library/playlist/<type:string>/<library_id:string>")
def api_get_playlist(request, type: str, library_id: str):

    if type not in ["music", "aux"]:
        abort(401)

    while not api_from_q.empty():
        api_from_q.get()  # Just waste any previous status responses.

    command = "GET_PLAYLIST_{}:{}".format(type.upper(), library_id)
    api_to_q.put(command)

    while True:
        try:
            response = api_from_q.get_nowait()
            if response.startswith(command):
                response = response[len(command) + 1:]
                if response == "null":
                    abort(401)
                return text(response)

        except Empty:
            pass

        sleep(0.02)


# JSON Outputs


@app.route("/status-json")
def json_status(request):
    channel_states = []
    for i in range(server_state.state["num_channels"]):
        channel_states.append(status(i))
    return resp_json({"server": server_state.state, "channels": channel_states})


# Get audio for UI to generate waveforms.


@app.route("/audiofile/<type:string>/<id:int>")
async def audio_file(request, type: str, id: int):
    if type not in ["managed", "track"]:
        abort(404)
    return await file("music-tmp/" + type + "-" + str(id) + ".mp3")


# Static Files
app.static("/favicon.ico", "./ui-static/favicon.ico", name="ui-favicon")
app.static("/static", "./ui-static", name="ui-static")
app.static("/presenter/", "./presenter-build/index.html", strict_slashes=True)
app.static("/presenter", "./presenter-build")


# Helper Functions

def status(channel: int):
    while not player_from_q[channel].empty():
        player_from_q[channel].get()  # Just waste any previous status responses.

    player_to_q[channel].put("UI:STATUS")
    retries = 0
    while retries < 40:
        try:
            response = player_from_q[channel].get_nowait()
            if response.startswith("UI:STATUS:"):
                response = response.split(":", 2)[2]
                # TODO: Handle OKAY / FAIL
                response = response[response.index(":") + 1:]
                try:
                    response = json.loads(response)
                except Exception as e:
                    raise e
                return response

        except Empty:
            pass

        retries += 1

        sleep(0.02)

# WebServer Start / Stop Functions


@app.route("/quit")
def quit(request):
    # stopServer()
    return "Shutting down..."


# Don't use reloader, it causes Nested Processes!
def WebServer(player_to: List[Queue], player_from: List[Queue], api_to: Queue, api_from: Queue, state: StateManager):

    global player_to_q, player_from_q, api_to_q, api_from_q, server_state
    player_to_q = player_to
    player_from_q = player_from
    api_from_q = api_from
    api_to_q = api_to
    server_state = state

    process_title = "Web Server"
    setproctitle(process_title)
    CORS(app, supports_credentials=True)  # Allow ALL CORS!!!

    # if not isBundelled():
    #    log = logging.getLogger("werkzeug")
    #    log.disabled = True

    #app.logger.disabled = True

    terminate = Terminator()
    while not terminate.terminate:
        try:
            app.run(
                host=server_state.state["host"],
                port=server_state.state["port"],
                debug=True,
                workers=1,
                auto_reload=False

                # use_reloader=False,
                # threaded=False  # While API handles are singlethreaded.
            )
        except Exception:
            break
    app.stop()
