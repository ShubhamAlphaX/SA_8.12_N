from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from datetime import datetime
from fetch_data import subscribe_symbols, get_expiry_data, fetch_all_stocks_data
from dateutil.relativedelta import relativedelta
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
import logging


app = Flask(__name__)
app.config["SECRET_KEY"] = "secret-key"
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

file_handler = RotatingFileHandler('app.log', maxBytes=94371840, backupCount=5)
time_handler = TimedRotatingFileHandler('app.log', when='h', interval=5, backupCount=5)

logger = logging.getLogger()
logger.addHandler(file_handler)
logger.addHandler(time_handler)

@app.route("/", methods=["GET"])
def home():
    expiry_data = get_expiry_data()
    return render_template("home.html", **expiry_data)


@socketio.on("message")
def message(data):

    expiry_option = data.get("expiry")
    open_factor = float(data.get("openFactor"))

    if expiry_option == "near":
        current_expiry = datetime.now().strftime("%y%b").upper()
        current_exp_date = data.get("near_expiry")
    elif expiry_option == "mid":
        current_expiry = (
            (datetime.now() + relativedelta(months=+1)).strftime("%y%b").upper()
        )
        current_exp_date = data.get("mid_expiry")
    elif expiry_option == "far":
        current_expiry = (
            (datetime.now() + relativedelta(months=+2)).strftime("%y%b").upper()
        )
        current_exp_date = data.get("far_expiry")
    else:
        emit("message", {"error": f"Unknown expiry option received: {expiry_option}"})
        return

    exp_date_dt = datetime.strptime(current_exp_date, "%Y-%m-%d")
    today_date = datetime.today()
    no_of_days_left = (exp_date_dt - today_date).days

    if current_expiry and no_of_days_left is not None and open_factor is not None:
        data = fetch_all_stocks_data(current_expiry, no_of_days_left, open_factor)
        socketio.emit("data", data)


if __name__ == "__main__":
    subscribe_symbols()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)


