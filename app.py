from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3, os, math
from datetime import datetime, date, timedelta
from contextlib import closing

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "parkiq.db")
app = Flask(__name__)
app.secret_key = os.environ.get("PARKIQ_SECRET", "change-this-demo-secret")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS UserAccount (
 user_id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
 phone TEXT, email TEXT UNIQUE, role TEXT NOT NULL DEFAULT 'DRIVER',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS Vehicle (
 vehicle_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
 plate_no TEXT NOT NULL UNIQUE, vehicle_type TEXT NOT NULL CHECK(vehicle_type IN ('CAR','BIKE','EV')),
 owner_name TEXT NOT NULL, owner_phone TEXT,
 FOREIGN KEY(user_id) REFERENCES UserAccount(user_id)
);
CREATE TABLE IF NOT EXISTS ParkingLot (
 lot_id INTEGER PRIMARY KEY AUTOINCREMENT, lot_name TEXT NOT NULL,
 location TEXT NOT NULL, total_slots INTEGER NOT NULL DEFAULT 30
);
CREATE TABLE IF NOT EXISTS ParkingSlot (
 slot_id INTEGER PRIMARY KEY AUTOINCREMENT, lot_id INTEGER NOT NULL,
 slot_no TEXT NOT NULL, slot_type TEXT NOT NULL CHECK(slot_type IN ('CAR','BIKE','EV')),
 floor_no INTEGER NOT NULL DEFAULT 0, dist_to_entry INTEGER NOT NULL DEFAULT 10,
 status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(status IN ('AVAILABLE','OCCUPIED','RESERVED','MAINTENANCE')),
 UNIQUE(lot_id,slot_no), FOREIGN KEY(lot_id) REFERENCES ParkingLot(lot_id)
);
CREATE TABLE IF NOT EXISTS Tariff (
 tariff_id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_type TEXT NOT NULL UNIQUE,
 rate_per_hour REAL NOT NULL, daily_cap REAL NOT NULL, grace_minutes INTEGER NOT NULL DEFAULT 15
);
CREATE TABLE IF NOT EXISTS Membership (
 membership_id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
 plan_name TEXT NOT NULL DEFAULT 'Monthly', discount_percent REAL NOT NULL DEFAULT 10,
 valid_from TEXT NOT NULL, valid_until TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
 FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id)
);
CREATE TABLE IF NOT EXISTS Reservation (
 reservation_id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
 slot_id INTEGER NOT NULL, reserved_from TEXT NOT NULL, reserved_until TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'CONFIRMED', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id), FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id)
);
CREATE TABLE IF NOT EXISTS ParkingTicket (
 ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
 slot_id INTEGER NOT NULL, entry_time TEXT NOT NULL, exit_time TEXT,
 status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')),
 FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id), FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id)
);
CREATE TABLE IF NOT EXISTS Payment (
 payment_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL UNIQUE,
 tariff_id INTEGER NOT NULL, amount REAL NOT NULL, pay_mode TEXT NOT NULL,
 paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(ticket_id) REFERENCES ParkingTicket(ticket_id),
 FOREIGN KEY(tariff_id) REFERENCES Tariff(tariff_id)
);
CREATE TABLE IF NOT EXISTS Penalty (
 penalty_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL,
 reason TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'PENDING',
 FOREIGN KEY(ticket_id) REFERENCES ParkingTicket(ticket_id)
);
CREATE TABLE IF NOT EXISTS Staff (
 staff_id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
 username TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('ADMIN','ATTENDANT','ANALYST'))
);
CREATE TABLE IF NOT EXISTS AuditLog (
 audit_id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL DEFAULT 'demo-admin',
 action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, details TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS SlotSensorEvent (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id INTEGER NOT NULL,
 sensor_state TEXT NOT NULL, event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 source TEXT NOT NULL DEFAULT 'SIMULATED', FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id)
);
CREATE INDEX IF NOT EXISTS idx_slot_status_type ON ParkingSlot(status,slot_type);
CREATE INDEX IF NOT EXISTS idx_ticket_open ON ParkingTicket(exit_time);
CREATE INDEX IF NOT EXISTS idx_vehicle_plate ON Vehicle(plate_no);
CREATE INDEX IF NOT EXISTS idx_payment_paid_at ON Payment(paid_at);
"""

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def audit(conn, action, entity, entity_id=None, details=""):
    conn.execute("INSERT INTO AuditLog(actor,action,entity,entity_id,details) VALUES(?,?,?,?,?)",
                 ("demo-admin", action, entity, entity_id, details))

def init_db():
    with closing(db()) as conn:
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM ParkingLot LIMIT 1").fetchone():
            conn.execute("INSERT INTO ParkingLot(lot_name,location,total_slots) VALUES(?,?,?)",
                         ("ParkIQ Central Parking","Hyderabad, Telangana",30))
            lot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for prefix, typ, count in [("A","CAR",18),("B","BIKE",8),("E","EV",4)]:
                for i in range(1,count+1):
                    conn.execute("""INSERT INTO ParkingSlot(lot_id,slot_no,slot_type,floor_no,dist_to_entry)
                                    VALUES(?,?,?,?,?)""",(lot_id,f"{prefix}-{i:02d}",typ,0, i*3))
            for typ, rate, cap, grace in [("CAR",30,250,15),("BIKE",15,120,15),("EV",35,280,15)]:
                conn.execute("INSERT INTO Tariff(vehicle_type,rate_per_hour,daily_cap,grace_minutes) VALUES(?,?,?,?)",
                             (typ,rate,cap,grace))
            conn.execute("INSERT INTO Staff(full_name,username,role) VALUES('ParkIQ Administrator','admin','ADMIN')")
            conn.execute("INSERT INTO Staff(full_name,username,role) VALUES('Parking Attendant','attendant','ATTENDANT')")
            # Sample parked vehicles for a useful first launch
            samples=[("TS09AB1234","CAR","Ravi Kumar","9000000001","A-01"),
                     ("TS10CD5678","BIKE","Ananya Rao","9000000002","B-01"),
                     ("TS08EF9012","EV","Kiran Reddy","9000000003","E-01")]
            for plate,typ,owner,phone,slotno in samples:
                conn.execute("INSERT INTO Vehicle(plate_no,vehicle_type,owner_name,owner_phone) VALUES(?,?,?,?)",
                             (plate,typ,owner,phone))
                vid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                slot=conn.execute("SELECT slot_id FROM ParkingSlot WHERE slot_no=?",(slotno,)).fetchone()
                conn.execute("UPDATE ParkingSlot SET status='OCCUPIED' WHERE slot_id=?",(slot["slot_id"],))
                conn.execute("INSERT INTO ParkingTicket(vehicle_id,slot_id,entry_time,status) VALUES(?,?,?,'OPEN')",
                             (vid,slot["slot_id"],(datetime.now()-timedelta(minutes=85)).isoformat(timespec="minutes")))
            audit(conn,"INITIALIZE","System",None,"Created demo lot and sample sessions")
        conn.commit()
init_db()

def fee_for(conn, ticket):
    vehicle=conn.execute("SELECT * FROM Vehicle WHERE vehicle_id=?",(ticket["vehicle_id"],)).fetchone()
    tariff=conn.execute("SELECT * FROM Tariff WHERE vehicle_type=?",(vehicle["vehicle_type"],)).fetchone()
    start=datetime.fromisoformat(ticket["entry_time"])
    end=datetime.fromisoformat(ticket["exit_time"]) if ticket["exit_time"] else datetime.now()
    mins=max(0,int((end-start).total_seconds()/60)-tariff["grace_minutes"])
    hours=math.ceil(mins/60) if mins else 0
    base=min(hours*tariff["rate_per_hour"],tariff["daily_cap"])
    member=conn.execute("""SELECT discount_percent FROM Membership WHERE vehicle_id=? AND status='ACTIVE'
                           AND valid_from<=? AND valid_until>=? ORDER BY membership_id DESC LIMIT 1""",
                         (vehicle["vehicle_id"],date.today().isoformat(),date.today().isoformat())).fetchone()
    discount=member["discount_percent"] if member else 0
    peak=1.5 if end.hour in (8,9,17,18,19) else 1.0
    penalty=conn.execute("SELECT COALESCE(SUM(amount),0) AS total FROM Penalty WHERE ticket_id=? AND status='PENDING'",
                         (ticket["ticket_id"],)).fetchone()["total"]
    return round(min(base*peak*(1-discount/100)+penalty, tariff["daily_cap"]+penalty),2), tariff["tariff_id"], hours, discount, peak

@app.route("/")
def dashboard():
    with closing(db()) as c:
        stats={
            "total":c.execute("SELECT COUNT(*) n FROM ParkingSlot").fetchone()["n"],
            "available":c.execute("SELECT COUNT(*) n FROM ParkingSlot WHERE status='AVAILABLE'").fetchone()["n"],
            "occupied":c.execute("SELECT COUNT(*) n FROM ParkingSlot WHERE status='OCCUPIED'").fetchone()["n"],
            "reserved":c.execute("SELECT COUNT(*) n FROM ParkingSlot WHERE status='RESERVED'").fetchone()["n"],
            "revenue":c.execute("SELECT COALESCE(SUM(amount),0) n FROM Payment WHERE date(paid_at)=date('now','localtime')").fetchone()["n"],
            "active":c.execute("SELECT COUNT(*) n FROM ParkingTicket WHERE status='OPEN'").fetchone()["n"],
        }
        sessions=c.execute("""SELECT t.*,v.plate_no,v.vehicle_type,v.owner_name,s.slot_no
                              FROM ParkingTicket t JOIN Vehicle v USING(vehicle_id)
                              JOIN ParkingSlot s USING(slot_id) WHERE t.status='OPEN' ORDER BY t.entry_time DESC LIMIT 6""").fetchall()
        by_type=c.execute("""SELECT slot_type, COUNT(*) total,
          SUM(CASE WHEN status='AVAILABLE' THEN 1 ELSE 0 END) available
          FROM ParkingSlot GROUP BY slot_type ORDER BY slot_type""").fetchall()
        recent=c.execute("""SELECT p.*,v.plate_no FROM Payment p JOIN ParkingTicket t USING(ticket_id)
                            JOIN Vehicle v USING(vehicle_id) ORDER BY p.payment_id DESC LIMIT 5""").fetchall()
    return render_template("dashboard.html",stats=stats,sessions=sessions,by_type=by_type,recent=recent,active="dashboard")

@app.route("/slots")
def slots():
    typ=request.args.get("type","ALL")
    with closing(db()) as c:
        q="""SELECT s.*,l.lot_name FROM ParkingSlot s JOIN ParkingLot l USING(lot_id)"""
        args=[]
        if typ!="ALL": q+=" WHERE s.slot_type=?";args.append(typ)
        q+=" ORDER BY s.slot_type,s.floor_no,s.dist_to_entry"
        rows=c.execute(q,args).fetchall()
    return render_template("slots.html",slots=rows,selected=typ,active="slots")

@app.route("/vehicles", methods=["GET","POST"])
def vehicles():
    if request.method=="POST":
        plate=request.form.get("plate","").strip().upper()
        typ=request.form.get("vehicle_type","CAR")
        owner=request.form.get("owner_name","").strip() or "Walk-in customer"
        phone=request.form.get("owner_phone","").strip()
        try:
            with closing(db()) as c:
                c.execute("INSERT INTO Vehicle(plate_no,vehicle_type,owner_name,owner_phone) VALUES(?,?,?,?)",(plate,typ,owner,phone))
                vid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                audit(c,"REGISTER","Vehicle",vid,f"{plate} / {typ}")
                c.commit()
            flash(f"Vehicle {plate} registered successfully.","success")
        except sqlite3.IntegrityError:
            flash("That registration number already exists. Use the existing vehicle record.","error")
        return redirect(url_for("vehicles"))
    q=request.args.get("q","").strip()
    with closing(db()) as c:
        rows=c.execute("""SELECT v.*, (SELECT COUNT(*) FROM ParkingTicket t WHERE t.vehicle_id=v.vehicle_id AND t.status='OPEN') active
                          FROM Vehicle v WHERE v.plate_no LIKE ? OR v.owner_name LIKE ? ORDER BY v.vehicle_id DESC""",
                       (f"%{q}%",f"%{q}%")).fetchall()
    return render_template("vehicles.html",vehicles=rows,q=q,active="vehicles")

@app.route("/entry", methods=["GET","POST"])
def entry():
    if request.method=="POST":
        plate=request.form.get("plate","").strip().upper()
        owner=request.form.get("owner_name","").strip() or "Walk-in customer"
        phone=request.form.get("owner_phone","").strip()
        typ=request.form.get("vehicle_type","CAR")
        now=datetime.now().isoformat(timespec="minutes")
        try:
            with closing(db()) as c:
                c.execute("BEGIN IMMEDIATE")
                v=c.execute("SELECT * FROM Vehicle WHERE plate_no=?",(plate,)).fetchone()
                if not v:
                    c.execute("INSERT INTO Vehicle(plate_no,vehicle_type,owner_name,owner_phone) VALUES(?,?,?,?)",(plate,typ,owner,phone))
                    vid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                else:
                    vid=v["vehicle_id"];typ=v["vehicle_type"]
                    if c.execute("SELECT 1 FROM ParkingTicket WHERE vehicle_id=? AND status='OPEN'",(vid,)).fetchone():
                        raise ValueError("This vehicle already has an active parking ticket.")
                slot=c.execute("""SELECT * FROM ParkingSlot WHERE status='AVAILABLE' AND slot_type=?
                                  ORDER BY floor_no ASC,dist_to_entry ASC LIMIT 1""",(typ,)).fetchone()
                if not slot: raise ValueError(f"No available {typ.lower()} slots. The lot may be full.")
                c.execute("UPDATE ParkingSlot SET status='OCCUPIED' WHERE slot_id=? AND status='AVAILABLE'",(slot["slot_id"],))
                if c.execute("SELECT changes()").fetchone()[0]!=1: raise ValueError("Slot allocation conflict. Please retry.")
                c.execute("INSERT INTO ParkingTicket(vehicle_id,slot_id,entry_time,status) VALUES(?,?,?,'OPEN')",(vid,slot["slot_id"],now))
                tid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute("INSERT INTO SlotSensorEvent(slot_id,sensor_state,source) VALUES(?,'OCCUPIED','APP')",(slot["slot_id"],))
                audit(c,"CHECK_IN","ParkingTicket",tid,f"{plate} allocated {slot['slot_no']}")
                c.commit()
            flash(f"Vehicle checked in. Ticket #{tid}, slot {slot['slot_no']}.","success")
            return redirect(url_for("sessions"))
        except (sqlite3.IntegrityError, ValueError) as e:
            flash(str(e) if isinstance(e,ValueError) else "Could not register this vehicle. Check its details.","error")
            return redirect(url_for("entry"))
    return render_template("entry.html",active="entry")

@app.route("/sessions")
def sessions():
    with closing(db()) as c:
        rows=c.execute("""SELECT t.*,v.plate_no,v.vehicle_type,v.owner_name,v.owner_phone,s.slot_no,
                          CAST((julianday('now','localtime')-julianday(t.entry_time))*24*60 AS INTEGER) mins
                          FROM ParkingTicket t JOIN Vehicle v USING(vehicle_id) JOIN ParkingSlot s USING(slot_id)
                          WHERE t.status='OPEN' ORDER BY t.entry_time""").fetchall()
    return render_template("sessions.html",sessions=rows,active="sessions")

@app.route("/checkout/<int:ticket_id>", methods=["GET","POST"])
def checkout(ticket_id):
    with closing(db()) as c:
        ticket=c.execute("""SELECT t.*,v.plate_no,v.vehicle_type,v.owner_name,s.slot_no
                            FROM ParkingTicket t JOIN Vehicle v USING(vehicle_id) JOIN ParkingSlot s USING(slot_id)
                            WHERE ticket_id=? AND t.status='OPEN'""",(ticket_id,)).fetchone()
        if not ticket:
            flash("Active ticket not found.","error"); return redirect(url_for("sessions"))
        amount, tariff_id, hours, discount, peak=fee_for(c,ticket)
        if request.method=="POST":
            mode=request.form.get("pay_mode","UPI")
            now=datetime.now().isoformat(timespec="minutes")
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE ParkingTicket SET exit_time=?,status='CLOSED' WHERE ticket_id=? AND status='OPEN'",(now,ticket_id))
            if c.execute("SELECT changes()").fetchone()[0]!=1:
                c.rollback();flash("Ticket was already checked out.","error");return redirect(url_for("sessions"))
            c.execute("INSERT INTO Payment(ticket_id,tariff_id,amount,pay_mode) VALUES(?,?,?,?)",(ticket_id,tariff_id,amount,mode))
            c.execute("UPDATE ParkingSlot SET status='AVAILABLE' WHERE slot_id=?",(ticket["slot_id"],))
            c.execute("INSERT INTO SlotSensorEvent(slot_id,sensor_state,source) VALUES(?,'AVAILABLE','APP')",(ticket["slot_id"],))
            audit(c,"CHECK_OUT","ParkingTicket",ticket_id,f"{ticket['plate_no']} paid ₹{amount} via {mode}")
            c.commit()
            flash(f"Checkout complete. Bill ₹{amount:.2f} recorded via {mode}.","success")
            return redirect(url_for("billing"))
    return render_template("checkout.html",ticket=ticket,amount=amount,hours=hours,discount=discount,peak=peak,active="sessions")

@app.route("/reservations", methods=["GET","POST"])
def reservations():
    if request.method=="POST":
        plate=request.form.get("plate","").strip().upper()
        typ=request.form.get("vehicle_type","CAR")
        start=request.form.get("reserved_from","")
        try:
            start_dt=datetime.fromisoformat(start)
            if start_dt < datetime.now()-timedelta(minutes=5): raise ValueError("Choose a future reservation time.")
            with closing(db()) as c:
                c.execute("BEGIN IMMEDIATE")
                v=c.execute("SELECT * FROM Vehicle WHERE plate_no=?",(plate,)).fetchone()
                if not v:
                    c.execute("INSERT INTO Vehicle(plate_no,vehicle_type,owner_name) VALUES(?,?,'Reservation customer')",(plate,typ))
                    vid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                else: vid=v["vehicle_id"];typ=v["vehicle_type"]
                slot=c.execute("SELECT * FROM ParkingSlot WHERE slot_type=? AND status='AVAILABLE' ORDER BY floor_no,dist_to_entry LIMIT 1",(typ,)).fetchone()
                if not slot: raise ValueError("No compatible slot is available to reserve.")
                c.execute("UPDATE ParkingSlot SET status='RESERVED' WHERE slot_id=?",(slot["slot_id"],))
                end_dt=start_dt+timedelta(minutes=30)
                c.execute("INSERT INTO Reservation(vehicle_id,slot_id,reserved_from,reserved_until,status) VALUES(?,?,?,?,'CONFIRMED')",
                          (vid,slot["slot_id"],start_dt.isoformat(timespec="minutes"),end_dt.isoformat(timespec="minutes")))
                rid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                audit(c,"RESERVE","Reservation",rid,f"{plate} / {slot['slot_no']}")
                c.commit()
            flash(f"Reservation confirmed for {plate} at slot {slot['slot_no']}. Hold window: 30 minutes.","success")
        except (ValueError, sqlite3.IntegrityError) as e:
            flash(str(e) if isinstance(e,ValueError) else "Could not create reservation.","error")
        return redirect(url_for("reservations"))
    with closing(db()) as c:
        rows=c.execute("""SELECT r.*,v.plate_no,v.vehicle_type,s.slot_no FROM Reservation r
                          JOIN Vehicle v USING(vehicle_id) JOIN ParkingSlot s USING(slot_id)
                          ORDER BY r.reservation_id DESC""").fetchall()
    return render_template("reservations.html",reservations=rows,active="reservations")

@app.route("/reservations/<int:rid>/cancel",methods=["POST"])
def cancel_reservation(rid):
    with closing(db()) as c:
        r=c.execute("SELECT * FROM Reservation WHERE reservation_id=? AND status='CONFIRMED'",(rid,)).fetchone()
        if r:
            c.execute("UPDATE Reservation SET status='CANCELLED' WHERE reservation_id=?",(rid,))
            c.execute("UPDATE ParkingSlot SET status='AVAILABLE' WHERE slot_id=? AND status='RESERVED'",(r["slot_id"],))
            audit(c,"CANCEL","Reservation",rid,"Reservation cancelled")
            c.commit();flash("Reservation cancelled and slot released.","success")
        else: flash("Active reservation not found.","error")
    return redirect(url_for("reservations"))

@app.route("/billing")
def billing():
    with closing(db()) as c:
        rows=c.execute("""SELECT p.*,v.plate_no,t.entry_time,t.exit_time,s.slot_no
                          FROM Payment p JOIN ParkingTicket t USING(ticket_id)
                          JOIN Vehicle v USING(vehicle_id) JOIN ParkingSlot s USING(slot_id)
                          ORDER BY p.payment_id DESC LIMIT 100""").fetchall()
        total=c.execute("SELECT COALESCE(SUM(amount),0) n FROM Payment").fetchone()["n"]
    return render_template("billing.html",payments=rows,total=total,active="billing")

@app.route("/settings",methods=["GET","POST"])
def settings():
    with closing(db()) as c:
        if request.method=="POST":
            for typ in ("CAR","BIKE","EV"):
                rate=float(request.form.get("rate_"+typ,30))
                cap=float(request.form.get("cap_"+typ,250))
                grace=int(request.form.get("grace_"+typ,15))
                if rate<0 or cap<0 or grace<0: flash("Tariffs must be non-negative.","error");return redirect(url_for("settings"))
                c.execute("UPDATE Tariff SET rate_per_hour=?,daily_cap=?,grace_minutes=? WHERE vehicle_type=?",(rate,cap,grace,typ))
            audit(c,"UPDATE","Tariff",None,"Tariff settings changed")
            c.commit();flash("Tariffs updated.","success");return redirect(url_for("settings"))
        tariffs=c.execute("SELECT * FROM Tariff ORDER BY vehicle_type").fetchall()
        staff=c.execute("SELECT * FROM Staff ORDER BY staff_id").fetchall()
        return render_template("settings.html",tariffs=tariffs,staff=staff,active="settings")

@app.route("/reports")
def reports():
    with closing(db()) as c:
        daily=c.execute("""SELECT date(paid_at) day, ROUND(SUM(amount),2) revenue,COUNT(*) transactions
                           FROM Payment GROUP BY date(paid_at) ORDER BY day DESC LIMIT 7""").fetchall()
        types=c.execute("""SELECT v.vehicle_type,COUNT(*) count,ROUND(AVG((julianday(t.exit_time)-julianday(t.entry_time))*24),2) avg_hours
                           FROM ParkingTicket t JOIN Vehicle v USING(vehicle_id) WHERE t.status='CLOSED'
                           GROUP BY v.vehicle_type""").fetchall()
        peak=c.execute("""SELECT CAST(strftime('%H',entry_time) AS INTEGER) hour,COUNT(*) count
                          FROM ParkingTicket GROUP BY hour ORDER BY count DESC LIMIT 5""").fetchall()
        audits=c.execute("SELECT * FROM AuditLog ORDER BY audit_id DESC LIMIT 10").fetchall()
    return render_template("reports.html",daily=daily,types=types,peak=peak,audits=audits,active="reports")

@app.route("/api/summary")
def api_summary():
    with closing(db()) as c:
        return jsonify({
          "slots":dict(c.execute("SELECT status,COUNT(*) count FROM ParkingSlot GROUP BY status").fetchall()[i] for i in range(c.execute("SELECT COUNT(DISTINCT status) FROM ParkingSlot").fetchone()[0])),
          "active_sessions":c.execute("SELECT COUNT(*) FROM ParkingTicket WHERE status='OPEN'").fetchone()[0],
          "revenue_today":c.execute("SELECT COALESCE(SUM(amount),0) FROM Payment WHERE date(paid_at)=date('now','localtime')").fetchone()[0]
        })

@app.route("/health")
def health():
    return {"app":"ParkIQ","status":"ok","database":"sqlite","mode":"local demo"}

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
