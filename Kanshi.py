from flask import Flask, render_template, flash, jsonify
import pandas as pd
from datetime import datetime, time, timedelta
import os
import json
import sqlite3
from contextlib import closing
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

print("Kanshi.py web interface started")
print(f"Current working directory: {__import__('os').getcwd()}")

DATABASE_FILE = '/home/reigicad/KoukiKanshi/machine_monitoring.db'

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize scheduler with timezone
scheduler = BackgroundScheduler(timezone='Asia/Tokyo')

def reset_all_machine_counters():
    """Reset counters for all machines at 6 AM."""
    print("reset_all_machine_counters function called")
    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            now = datetime.now()
            reset_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
            
            # Get current machine states before reset
            cursor.execute("SELECT machine_id, current_status FROM machine_runtime")
            current_states = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Reset counters but preserve current status
            for machine_id, current_status in current_states.items():
                cursor.execute("""
                    UPDATE machine_runtime 
                    SET off_duration = 0,
                        prep_duration = 0,
                        on_duration = 0,
                        unknown_duration = 0,
                        last_reset_time = ?,
                        current_start_time = ?
                    WHERE machine_id = ?
                """, (reset_time.isoformat(), reset_time.isoformat(), machine_id))
            
            conn.commit()
            print(f"Reset performed at {now}, reset_time set to {reset_time}")
            return True
            
    except sqlite3.Error as e:
        error_msg = f"Error resetting daily counters: {e}"
        print(error_msg)
        return False

print("Setting up scheduler...")  # Server-side log
# Schedule the reset job to run at 15:30 every day
scheduler.add_job(reset_all_machine_counters, 'cron', hour=6, minute=0)
scheduler.start()
print(f"Scheduler started at {datetime.now()}. Next reset scheduled for 06:00")
print("Active jobs:", scheduler.get_jobs())  # Server-side log

# Ensure scheduler shuts down properly
atexit.register(lambda: scheduler.shutdown())

def is_working_hours():
    """Check if current time is within working hours (6 AM - 6 PM)"""
    now = datetime.now()
    start_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
    return start_time <= now <= end_time

def get_db_connection():
    """Get a new database connection."""
    return sqlite3.connect(DATABASE_FILE)

def get_machine_history(machine_id=None):
    """Get today's history for machine(s)."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    machine_ids = ["GRS_14", "GRS_17", "GRS_19"] if machine_id is None else [machine_id]
    history_data = {}
    
    try:
        with closing(get_db_connection()) as conn:
            for mid in machine_ids:
                cursor = conn.execute(
                    "SELECT timestamp, status FROM machine_events "
                    "WHERE machine_id = ? AND timestamp BETWEEN ? AND ? "
                    "ORDER BY timestamp",
                    (mid, today_start.isoformat(), today_end.isoformat())
                )
                history_data[mid] = [{
                    "timestamp": datetime.fromisoformat(row[0]),
                    "status": row[1]
                } for row in cursor.fetchall()]
    except sqlite3.Error as e:
        app.logger.error(f"Database error: {e}")
    return history_data if machine_id is None else history_data.get(machine_id, [])

def generate_timeline_data(machine_ids=None):
    """Generate timeline data for specified machines."""
    machine_ids = machine_ids or ["GRS_14", "GRS_17", "GRS_19"]
    timeline_data = {}

    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            now = datetime.now()
            start_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
            
            for machine_id in machine_ids:
                # Initialize timeline with 144 slots (12 hours * 12 intervals per hour)
                timeline = []
                current_time = start_time
                interval = timedelta(minutes=5)

                # Get the last known state from previous day
                yesterday = now - timedelta(days=1)
                cursor.execute("""
                    SELECT timestamp, status 
                    FROM machine_events 
                    WHERE machine_id = ? 
                    AND timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (machine_id, start_time.isoformat()))
                
                last_state = cursor.fetchone()
                last_state_before_start = last_state[1] if last_state else 'UNKNOWN'

                # Get today's events
                cursor.execute("""
                    SELECT timestamp, status 
                    FROM machine_events 
                    WHERE machine_id = ? 
                    AND timestamp >= ?
                    AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (machine_id, start_time.isoformat(), now.isoformat()))
                
                events = [(datetime.fromisoformat(ts), status) for ts, status in cursor.fetchall()]

                # Get current state
                cursor.execute(
                    "SELECT current_status, current_start_time FROM machine_runtime WHERE machine_id = ?",
                    (machine_id,)
                )
                current_result = cursor.fetchone()
                if current_result:
                    current_status = current_result[0]
                    current_start = datetime.fromisoformat(current_result[1])
                    # Add current state if it's the most recent
                    if not events or current_start > events[-1][0]:
                        events.append((current_start, current_status))

                # Fill timeline slots
                current_status = last_state_before_start
                while current_time <= now and current_time < end_time:
                    next_time = current_time + interval
                    
                    # Update status if there are any events in this interval
                    for event_time, event_status in events:
                        if current_time <= event_time < next_time:
                            current_status = event_status
                    
                    timeline.append(current_status)
                    current_time = next_time

                # Fill remaining slots with None
                while len(timeline) < 144:  # 12 hours * 12 intervals
                    timeline.append(None)

                timeline_data[machine_id] = timeline

    except sqlite3.Error as e:
        app.logger.error(f"Error generating timeline data: {e}")
        return {machine_id: [None] * 144 for machine_id in machine_ids}

    return timeline_data

def get_machine_runtime_data(machine_id):
    """Get runtime data for a specific machine."""
    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT off_duration, prep_duration, on_duration, unknown_duration,
                       current_status, current_start_time, last_reset_time
                FROM machine_runtime
                WHERE machine_id = ?""", 
                (machine_id,)
            )
            result = cursor.fetchone()
            
            if result:
                off_duration, prep_duration, on_duration, unknown_duration, current_status, current_start_time, last_reset_time = result
                
                # Calculate current state duration only if within working hours
                now = datetime.now()
                if current_status and current_start_time and is_working_hours():
                    current_start = datetime.fromisoformat(current_start_time)
                    
                    # Ensure we don't count time before today's 6 AM
                    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
                    if current_start < today_6am:
                        current_start = today_6am
                    
                    # Ensure we don't count time after 6 PM
                    today_6pm = now.replace(hour=18, minute=0, second=0, microsecond=0)
                    end_time = min(now, today_6pm)
                    
                    current_duration = (end_time - current_start).total_seconds()
                    
                    # Only add current duration if it's positive
                    if current_duration > 0:
                        if current_status == "Off":
                            off_duration += current_duration
                        elif current_status == "Prep":
                            prep_duration += current_duration
                        elif current_status == "On":
                            on_duration += current_duration
                        elif current_status == "Unknown":
                            unknown_duration += current_duration
                
                return {
                    "durations": {
                        "Off": round(off_duration),
                        "Prep": round(prep_duration),
                        "On": round(on_duration),
                        "Unknown": round(unknown_duration)
                    }
                }
            return {"durations": {"Off": 0, "Prep": 0, "On": 0, "Unknown": 0}}
    except Exception as e:
        print(f"Error getting runtime data: {e}")
        return {"durations": {"Off": 0, "Prep": 0, "On": 0, "Unknown": 0}}

def fetch_current_data():
    """Fetch current state of all machines."""
    machine_data = {}
    now = datetime.now()

    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            for machine_id in ["GRS_14", "GRS_17", "GRS_19"]:
                cursor.execute("""
                    SELECT current_status
                    FROM machine_runtime
                    WHERE machine_id = ?
                """, (machine_id,))
                result = cursor.fetchone()
                condition = result[0] if result else "Unknown"
                
                runtime_data = get_machine_runtime_data(machine_id)
                machine_data[machine_id] = {
                    "condition": condition,
                    "timestamp": now,
                    "total_durations": runtime_data["durations"]
                }
    except sqlite3.Error as e:
        app.logger.error(f"Database error in fetch_current_data: {e}")
        
    return pd.DataFrame.from_dict(machine_data, orient='index').reset_index().rename(columns={'index': 'machine_id'})

@app.route("/")
def dashboard():
    """Main dashboard route."""
    df = fetch_current_data()
    return render_template(
        "dashboard.html",
        latest_data=df.to_dict('records'),
        latest_timestamp=df['timestamp'].iloc[0] if not df.empty else None,
        machine_conditions=df.set_index('machine_id')['condition'].to_dict(),
        timeline_data=generate_timeline_data()
    )

@app.route("/update_conditions")
def update_conditions():
    """API endpoint for updating machine conditions."""
    try:
        now = datetime.now()
        
        # Check if we need to trigger a reset
        reset_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
        time_diff = (now - reset_time).total_seconds()
        
        # Consider reset time if we're within 5 seconds after the target time
        # or if we're up to 1 minute past and no reset has occurred
        just_reset = (0 <= time_diff <= 5)
        
        # Get last reset time from database
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_reset_time FROM machine_runtime LIMIT 1")
            last_reset = cursor.fetchone()
            last_reset_time = datetime.fromisoformat(last_reset[0]) if last_reset and last_reset[0] else None
            
            # Force reset if we're past reset time and haven't reset yet
            if last_reset_time and last_reset_time.date() < now.date():
                if 0 <= time_diff <= 60:  # Within 1 minute after reset time
                    print("Forcing reset - past reset time and no reset today")
                    just_reset = True
        
        # If it's reset time or we need to force a reset, perform the reset
        if just_reset:
            print(f"Reset triggered at {now} (time_diff: {time_diff}s)")
            reset_all_machine_counters()
            
            # Double-check the reset was applied
            with closing(get_db_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT SUM(off_duration + prep_duration + on_duration + unknown_duration) FROM machine_runtime")
                total = cursor.fetchone()[0]
                if total > 0:
                    print("Reset verification failed - retrying reset")
                    reset_all_machine_counters()
        
        # Fetch latest data after potential reset
        df = fetch_current_data()
        conditions = df.set_index('machine_id')['condition'].to_dict()
        total_durations = {
            machine: get_machine_runtime_data(machine)["durations"]
            for machine in ["GRS_14", "GRS_17", "GRS_19"]
        }
        
        # Add debug information to the response
        debug_info = {
            "current_time": now.isoformat(),
            "reset_check_time": reset_time.isoformat(),
            "time_diff_seconds": time_diff,
            "just_reset": just_reset,
            "last_reset_time": last_reset_time.isoformat() if last_reset_time else None,
            "scheduler_jobs": str(scheduler.get_jobs()),
            "next_run_time": str(scheduler.get_jobs()[0].next_run_time) if scheduler.get_jobs() else "No jobs scheduled"
        }
        
        print(f"Debug info: {debug_info}")
        
        return jsonify({
            "machine_conditions": conditions,
            "latest_timestamp": now.strftime("%Y-%m-%d %H:%M:%S (JST)"),
            "timeline_data": generate_timeline_data(),
            "total_durations": total_durations,
            "debug_info": debug_info,
            "just_reset": just_reset
        })
    except Exception as e:
        app.logger.error(f"Error in update_conditions: {e}")
        return jsonify({"error": str(e), "debug_info": {"error_time": datetime.now().isoformat()}}), 500

@app.route("/reset_counters", methods=['POST'])
def reset_counters():
    """Manually reset all machine counters."""
    try:
        reset_all_machine_counters()
        return jsonify({"status": "success", "message": "All machine counters have been reset"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/history")
def history():
    """History page route."""
    return render_template("history.html")

@app.route("/api/history/dates")
def get_available_dates():
    """Get list of dates that have machine data."""
    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            # Only get dates before today that have data
            cursor.execute("""
                SELECT DISTINCT date(timestamp) as date
                FROM machine_events
                WHERE timestamp >= date('now', '-30 days')
                AND date(timestamp) < date('now')
                ORDER BY date DESC
            """)
            dates = [row[0] for row in cursor.fetchall()]
            return jsonify({"dates": dates})
    except Exception as e:
        app.logger.error(f"Error getting available dates: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/history/data/<date>")
def get_history_data(date):
    """Get machine data for a specific date."""
    try:
        # If requesting today's date, return empty data
        today = datetime.now().strftime('%Y-%m-%d')
        if date == today:
            return jsonify({
                machine_id: [] for machine_id in ["GRS_14", "GRS_17", "GRS_19"]
            })

        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            
            # Get the start and end of the working day (6 AM to 6 PM)
            start_time = datetime.strptime(f"{date} 06:00:00", "%Y-%m-%d %H:%M:%S")
            end_time = datetime.strptime(f"{date} 18:00:00", "%Y-%m-%d %H:%M:%S")
            
            history_data = {}
            for machine_id in ["GRS_14", "GRS_17", "GRS_19"]:
                # Get the last known state before the start time
                cursor.execute("""
                    SELECT timestamp, status
                    FROM machine_events
                    WHERE machine_id = ? AND timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (machine_id, start_time.isoformat()))
                last_state = cursor.fetchone()
                
                # Get all events during the working hours
                cursor.execute("""
                    SELECT timestamp, status, 
                           LEAD(timestamp) OVER (ORDER BY timestamp) as next_timestamp
                    FROM machine_events
                    WHERE machine_id = ? 
                    AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                """, (machine_id, start_time.isoformat(), end_time.isoformat()))
                
                events = []
                total_durations = {"Off": 0, "Prep": 0, "On": 0, "Unknown": 0}
                
                # Add initial state at 6 AM if we have a previous state
                if last_state:
                    events.append({
                        "timestamp": start_time.isoformat(),
                        "status": last_state[1],
                        "duration": 0
                    })
                    current_status = last_state[1]
                else:
                    current_status = "Unknown"
                
                current_time = start_time
                
                # Process all events and calculate durations
                rows = cursor.fetchall()
                for i, row in enumerate(rows):
                    event_time = datetime.fromisoformat(row[0])
                    status = row[1]
                    next_time = (datetime.fromisoformat(row[2]) 
                               if row[2] else end_time)
                    
                    # Calculate duration for the previous status
                    duration = (event_time - current_time).total_seconds()
                    if current_status in total_durations:
                        total_durations[current_status] += duration
                    
                    events.append({
                        "timestamp": event_time.isoformat(),
                        "status": status,
                        "duration": duration
                    })
                    
                    current_time = event_time
                    current_status = status
                
                # Add final duration until end time
                final_duration = (end_time - current_time).total_seconds()
                if current_status in total_durations:
                    total_durations[current_status] += final_duration
                
                history_data[machine_id] = {
                    "events": events,
                    "durations": total_durations
                }
            
            return jsonify(history_data)
            
    except Exception as e:
        app.logger.error(f"Error getting history data: {e}")
        return jsonify({"error": str(e)}), 500
        
if __name__ == "__main__":
    try:
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        app.logger.error(f"Error starting web server: {e}")
