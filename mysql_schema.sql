-- ParkIQ relational schema (MySQL 8)
CREATE DATABASE IF NOT EXISTS parkiq_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE parkiq_db;

CREATE TABLE UserAccount (
  user_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  full_name VARCHAR(120) NOT NULL, phone VARCHAR(25), email VARCHAR(160) UNIQUE,
  role ENUM('DRIVER','ATTENDANT','ADMIN','ANALYST') NOT NULL DEFAULT 'DRIVER',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE Vehicle (
  vehicle_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NULL, plate_no VARCHAR(20) NOT NULL UNIQUE,
  vehicle_type ENUM('CAR','BIKE','EV') NOT NULL,
  owner_name VARCHAR(120) NOT NULL, owner_phone VARCHAR(25),
  CONSTRAINT fk_vehicle_user FOREIGN KEY(user_id) REFERENCES UserAccount(user_id)
);
CREATE TABLE ParkingLot (
  lot_id BIGINT PRIMARY KEY AUTO_INCREMENT, lot_name VARCHAR(120) NOT NULL,
  location VARCHAR(255) NOT NULL, total_slots INT NOT NULL CHECK(total_slots>=0)
);
CREATE TABLE ParkingSlot (
  slot_id BIGINT PRIMARY KEY AUTO_INCREMENT, lot_id BIGINT NOT NULL,
  slot_no VARCHAR(20) NOT NULL, slot_type ENUM('CAR','BIKE','EV') NOT NULL,
  floor_no TINYINT NOT NULL DEFAULT 0, dist_to_entry SMALLINT NOT NULL DEFAULT 10,
  status ENUM('AVAILABLE','OCCUPIED','RESERVED','MAINTENANCE') NOT NULL DEFAULT 'AVAILABLE',
  UNIQUE KEY uq_lot_slot(lot_id,slot_no),
  KEY idx_slot_status_type(status,slot_type,floor_no,dist_to_entry),
  CONSTRAINT fk_slot_lot FOREIGN KEY(lot_id) REFERENCES ParkingLot(lot_id)
);
CREATE TABLE Tariff (
  tariff_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  vehicle_type ENUM('CAR','BIKE','EV') NOT NULL UNIQUE,
  rate_per_hour DECIMAL(10,2) NOT NULL CHECK(rate_per_hour>=0),
  daily_cap DECIMAL(10,2) NOT NULL CHECK(daily_cap>=0),
  grace_minutes INT NOT NULL DEFAULT 15 CHECK(grace_minutes>=0)
);
CREATE TABLE Membership (
  membership_id BIGINT PRIMARY KEY AUTO_INCREMENT, vehicle_id BIGINT NOT NULL,
  plan_name VARCHAR(80) NOT NULL DEFAULT 'Monthly', discount_percent DECIMAL(5,2) NOT NULL DEFAULT 10,
  valid_from DATE NOT NULL, valid_until DATE NOT NULL,
  status ENUM('ACTIVE','EXPIRED','CANCELLED') NOT NULL DEFAULT 'ACTIVE',
  CONSTRAINT fk_member_vehicle FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id),
  CHECK(valid_until>=valid_from), CHECK(discount_percent BETWEEN 0 AND 100)
);
CREATE TABLE Reservation (
  reservation_id BIGINT PRIMARY KEY AUTO_INCREMENT, vehicle_id BIGINT NOT NULL, slot_id BIGINT NOT NULL,
  reserved_from DATETIME NOT NULL, reserved_until DATETIME NOT NULL,
  status ENUM('CONFIRMED','CHECKED_IN','CANCELLED','EXPIRED') NOT NULL DEFAULT 'CONFIRMED',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_reservation_window(status,reserved_from,reserved_until),
  CONSTRAINT fk_res_vehicle FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id),
  CONSTRAINT fk_res_slot FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id),
  CHECK(reserved_until>reserved_from)
);
CREATE TABLE ParkingTicket (
  ticket_id BIGINT PRIMARY KEY AUTO_INCREMENT, vehicle_id BIGINT NOT NULL, slot_id BIGINT NOT NULL,
  entry_time DATETIME NOT NULL, exit_time DATETIME NULL,
  status ENUM('OPEN','CLOSED') NOT NULL DEFAULT 'OPEN',
  KEY idx_ticket_open(status,exit_time), KEY idx_ticket_vehicle(vehicle_id,status),
  CONSTRAINT fk_ticket_vehicle FOREIGN KEY(vehicle_id) REFERENCES Vehicle(vehicle_id),
  CONSTRAINT fk_ticket_slot FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id),
  CHECK(exit_time IS NULL OR exit_time>entry_time)
);
CREATE TABLE Payment (
  payment_id BIGINT PRIMARY KEY AUTO_INCREMENT, ticket_id BIGINT NOT NULL UNIQUE,
  tariff_id BIGINT NOT NULL, amount DECIMAL(10,2) NOT NULL CHECK(amount>=0),
  pay_mode ENUM('UPI','CARD','CASH') NOT NULL, paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_payment_ticket FOREIGN KEY(ticket_id) REFERENCES ParkingTicket(ticket_id),
  CONSTRAINT fk_payment_tariff FOREIGN KEY(tariff_id) REFERENCES Tariff(tariff_id)
);
CREATE TABLE Penalty (
  penalty_id BIGINT PRIMARY KEY AUTO_INCREMENT, ticket_id BIGINT NOT NULL,
  reason VARCHAR(255) NOT NULL, amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  status ENUM('PENDING','PAID','WAIVED') NOT NULL DEFAULT 'PENDING',
  CONSTRAINT fk_penalty_ticket FOREIGN KEY(ticket_id) REFERENCES ParkingTicket(ticket_id),
  CHECK(amount>=0)
);
CREATE TABLE Staff (
  staff_id BIGINT PRIMARY KEY AUTO_INCREMENT, full_name VARCHAR(120) NOT NULL,
  username VARCHAR(80) NOT NULL UNIQUE,
  role ENUM('ADMIN','ATTENDANT','ANALYST') NOT NULL
);
CREATE TABLE AuditLog (
  audit_id BIGINT PRIMARY KEY AUTO_INCREMENT, actor VARCHAR(120) NOT NULL,
  action VARCHAR(60) NOT NULL, entity VARCHAR(60) NOT NULL, entity_id BIGINT NULL,
  details TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE SlotSensorEvent (
  event_id BIGINT PRIMARY KEY AUTO_INCREMENT, slot_id BIGINT NOT NULL,
  sensor_state ENUM('AVAILABLE','OCCUPIED') NOT NULL,
  event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, source VARCHAR(40) NOT NULL DEFAULT 'SIMULATED',
  CONSTRAINT fk_sensor_slot FOREIGN KEY(slot_id) REFERENCES ParkingSlot(slot_id)
);

CREATE OR REPLACE VIEW vw_available_slots AS
SELECT l.lot_name,s.slot_id,s.slot_no,s.slot_type,s.floor_no,s.dist_to_entry
FROM ParkingSlot s JOIN ParkingLot l USING(lot_id) WHERE s.status='AVAILABLE';
CREATE OR REPLACE VIEW vw_active_sessions AS
SELECT t.ticket_id,v.plate_no,v.vehicle_type,s.slot_no,t.entry_time
FROM ParkingTicket t JOIN Vehicle v USING(vehicle_id) JOIN ParkingSlot s USING(slot_id)
WHERE t.status='OPEN';
CREATE OR REPLACE VIEW vw_daily_revenue AS
SELECT DATE(paid_at) revenue_day, SUM(amount) revenue, COUNT(*) payments
FROM Payment GROUP BY DATE(paid_at);

-- Example safe allocation transaction. Run as a stored procedure in the application
-- or convert into a MySQL procedure; FOR UPDATE prevents two transactions claiming one row.
-- START TRANSACTION;
-- SELECT slot_id,slot_no INTO @slot_id,@slot_no FROM ParkingSlot
-- WHERE status='AVAILABLE' AND slot_type='CAR'
-- ORDER BY floor_no,dist_to_entry LIMIT 1 FOR UPDATE SKIP LOCKED;
-- UPDATE ParkingSlot SET status='OCCUPIED' WHERE slot_id=@slot_id AND status='AVAILABLE';
-- INSERT INTO ParkingTicket(vehicle_id,slot_id,entry_time,status) VALUES(@vehicle_id,@slot_id,NOW(),'OPEN');
-- COMMIT;

CREATE INDEX idx_payment_paid_at ON Payment(paid_at);
CREATE INDEX idx_vehicle_plate ON Vehicle(plate_no);
