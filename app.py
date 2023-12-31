from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import join_room, leave_room, send, SocketIO
import random
from string import ascii_uppercase
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime  
import time 

app = Flask(__name__)
# variable configurations are hidden
app.config["SECRET_KEY"] = 
app.config["SQLALCHEMY_DATABASE_URI"] =

db = SQLAlchemy(app)
socketio = SocketIO(app)

rooms = {}

# create tables through SQLAlchemy to store room participants and room status
class RoomParticipants(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(6), nullable=False)
    username = db.Column(db.String(255), nullable=False)
    identity = db.Column(db.String(255), nullable=False)
    has_buzzed_in = db.Column(db.Boolean, default=False)

class RoomStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(6), nullable=False)
    status = db.Column(db.String(255), nullable=False)

@app.route("/", methods=["POST", "GET"])
def home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template("home.html", error="Please enter a name.", code=code, name=name)

        if join != False and not code:
            return render_template("home.html", error="Please enter a room code.", code=code, name=name)
        
        room = code
        # update room status to "restricted" to prevent users from entering
        if RoomStatus.query.filter_by(room_number=room, status="restricted").first():
            return render_template("home.html", error="Game already started.", code=code, name=name)
        if create != False:
            room = code  
            rooms[room] = {"members": 0, "messages": []}
        elif code not in rooms:
            return render_template("home.html", error="Room does not exist.", code=code, name=name)
        if create != False:
            identity = "host"
        else: 
            identity = "participant"
        
        session["identity"] = identity
        session["room"] = room
        session["name"] = name

        if create != False and RoomParticipants.query.filter_by(room_number=room).first() is not None:
            return render_template("home.html", error="Room number taken.<br>Please enter another code.", code=code, name=name)
        new_participant = RoomParticipants(room_number=room, username=name, identity = identity)
        db.session.add(new_participant)
        db.session.commit()     
        return redirect(url_for("room"))

    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))

    return render_template("room.html", code=room, messages=rooms[room]["messages"])

@app.route("/create_game", methods=["POST"])
def create_game():
    room = request.json.get("room")
    identity = RoomParticipants.query.filter_by(room_number=room).first().identity

    if identity == "host":
        # Resets buzz in status
        participants = RoomParticipants.query.filter_by(room_number=room).all()
        for participant in participants:
            participant.has_buzzed_in = False
            db.session.commit()

        # Update room status to "restricted" in database
        room_status = RoomStatus(room_number=room, status="restricted")
        db.session.add(room_status)
        db.session.commit()

        socketio.emit("room_status_update", {"room": room, "status": "restricted"}, namespace="/")
        print("Create room status update")

@app.route("/reset_game", methods=["POST"])
def reset_game():
    room = request.json.get("room")
    identity = RoomParticipants.query.filter_by(room_number=room).first().identity

    if identity == "host":
        # Deletes 'restricted' row from room_status table
        room_status_entry = RoomStatus.query.filter_by(room_number=room).first()
        if room_status_entry:

            db.session.commit()
            socketio.emit("room_status_update", {"room": room, "status": "unrestricted"}, namespace="/")
            db.session.delete(room_status_entry)
            db.session.commit()


@socketio.on("message")
def message(data):
    room = session.get("room")
    if room not in rooms:
        return

    content = {
        "name": session.get("name"),
        "message": data["data"],
        "timestamp": time.time() * 1000  # Milisecond accuracy for buzz in time
    }
    send(content, to=room)
    rooms[room]["messages"].append(content)

    if data["data"] == "Game started!" and session.get("identity") == "host":
        socketio.emit("game_started", room=room, namespace="/")

    print(f"{session.get('name')} said: {data['data']}")

@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return
    
    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms[room]["members"] += 1
    print(f"{name} joined room {room}")

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    identity = session.get("identity")

    if room in rooms:
        rooms[room]["members"] -= 1
        if identity == "host":
            # Removes all room records once the host disconnects
            RoomStatus.query.filter_by(room_number=room).delete()
            RoomParticipants.query.filter_by(room_number=room).delete()
            db.session.commit()

            socketio.emit("host_left", room=room, namespace="/")
            del rooms[room]  
        else:
            # Removes all participants once the host disconnects
            send({"name": name, "message": "has left the room"}, to=room)
    leave_room(room)
    print(f"{name} has left the room {room}")
if __name__ == "__main__":
    socketio.run(app, debug=True)
