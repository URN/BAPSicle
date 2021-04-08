#!/usr/bin/env python3
import multiprocessing
import time
import sys
import webbrowser
from setproctitle import setproctitle

from server import BAPSicleServer


def startServer():
    server = multiprocessing.Process(target=BAPSicleServer)
    server.start()

    try:
        while True:
            time.sleep(5)
            if server and server.is_alive():
                pass
            else:
                print("Server dead. Exiting.")
                sys.exit(0)
        # Catch the handler being killed externally.
    except KeyboardInterrupt:
        print("Received KeyboardInterupt")
    except SystemExit:
        print("Received SystemExit")
    except Exception as e:
        print("Received unexpected exception: {}".format(e))


if __name__ == "__main__":
    # On Windows, calling this function is necessary.
    # Causes all kinds of loops if not present.
    # IT HAS TO BE RIGHT HERE, AT THE TOP OF __MAIN__
    # NOT INSIDE AN IF STATEMENT. RIGHT. HERE.
    # If it's not here, multiprocessing just doesn't run in the package.
    # Freeze support refers to being packaged with Pyinstaller.
    multiprocessing.freeze_support()
    setproctitle("BAPSicle - Standalone Launch")
    if len(sys.argv) > 1:
        # We got an argument! It's probably Platypus's UI.
        try:
            if (sys.argv[1]) == "Start Server":
                print("NOTIFICATION:Welcome to BAPSicle!")
                webbrowser.open("http://localhost:13500/")
                startServer()
            if sys.argv[1] == "Status":
                webbrowser.open("http://localhost:13500/status")
            if sys.argv[1] == "Config":
                webbrowser.open("http://localhost:13500/config")
            if sys.argv[1] == "Logs":
                webbrowser.open("http://localhost:13500/logs")
        except Exception as e:
            print("ALERT:BAPSicle failed with exception:\n", e)
            sys.exit(1)

        sys.exit(0)
    else:
        startServer()
