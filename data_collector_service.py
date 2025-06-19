import RPi.GPIO as GPIO
import sqlite3
from datetime import datetime, timedelta
import time
import logging
from logging.handlers import RotatingFileHandler
import sys
import os
from contextlib import closing

# Configure logging
log_file = '/home/reigicad/KoukiKanshi/data_collector.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('DataCollector')

# GPIO Pin Definitions
GRS_14Lamp = 5
GRS_14Switch = 6
GRS_17Lamp = 13
GRS_17Switch = 19
GRS_19Lamp = 16
GRS_19Switch = 20
# Separate pins into different groups based on pull-up/pull-down requirements
PULLDOWN_PINS = [GRS_17Lamp, GRS_17Switch, GRS_19Lamp, GRS_19Switch]
PULLUP_PINS = [GRS_14Lamp, GRS_14Switch]

# Configuration
DATABASE_FILE = '/home/reigicad/KoukiKanshi/machine_monitoring.db'
SAMPLE_DURATION = 8
SAMPLE_RATE = 0.08
MAJORITY_THRESHOLD = 0.7
COLLECTION_INTERVAL = 10  # Collect data every 10 seconds

def setup_gpio():
    """Initialize GPIO settings"""
    try:
        GPIO.setmode(GPIO.BCM)
        # Setup pull-down pins
        for pin in PULLDOWN_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        # Setup pull-up pins
        for pin in PULLUP_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        logger.info("GPIO setup completed successfully")
    except Exception as e:
        logger.error(f"Error setting up GPIO: {e}")
        sys.exit(1)

def get_db_connection():
    """Get a new database connection"""
    return sqlite3.connect(DATABASE_FILE)

def is_working_hours():
    """Check if current time is within working hours (6 AM - 6 PM)"""
    now = datetime.now()
    start_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
    return start_time <= now <= end_time

def get_machine_condition(lamp_pin, switch_pin, invert=False):
    """Read machine condition using majority voting"""
    try:
        lamp_readings = []
        switch_readings = []
        num_samples = int(SAMPLE_DURATION / SAMPLE_RATE)

        for _ in range(num_samples):
            lamp_value = GPIO.input(lamp_pin)
            switch_value = GPIO.input(switch_pin)
            # Invert the readings if needed (for GRS_14)
            if invert:
                lamp_value = not lamp_value
                switch_value = not switch_value
            lamp_readings.append(lamp_value)
            switch_readings.append(switch_value)
            time.sleep(SAMPLE_RATE)

        lamp_on_count = sum(lamp_readings)
        switch_on_count = sum(switch_readings)
        lamp_is_on = lamp_on_count >= (num_samples * MAJORITY_THRESHOLD)
        switch_is_on = switch_on_count >= (num_samples * MAJORITY_THRESHOLD)

        if not lamp_is_on and switch_is_on:
            return "Off"
        elif not lamp_is_on and not switch_is_on:
            return "Prep"
        elif lamp_is_on and not switch_is_on:
            return "On"
        return "Unknown"
    except Exception as e:
        logger.error(f"Error reading machine condition: {e}")
        return "Unknown"

def log_status_change(machine_id, status, max_retries=3, retry_delay=0.01):
    """Log machine status change to database with retry mechanism"""
    if not is_working_hours():
        return

    attempts = 0
    while attempts < max_retries:
        try:
            with closing(get_db_connection()) as conn:
                cursor = conn.cursor()
                current_time = datetime.now()
                
                # Begin transaction
                cursor.execute("BEGIN TRANSACTION")
                
                # Get current status, start time, and existing durations
                cursor.execute(
                    """SELECT current_status, current_start_time,
                              off_duration, prep_duration, on_duration, unknown_duration 
                       FROM machine_runtime 
                       WHERE machine_id = ?""", 
                    (machine_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    previous_status = result[0]
                    previous_start_time_str = result[1]
                    current_durations = {
                        'off': result[2] or 0,
                        'prep': result[3] or 0,
                        'on': result[4] or 0,
                        'unknown': result[5] or 0
                    }
                    previous_start_time = datetime.fromisoformat(previous_start_time_str) if previous_start_time_str else None
                else:
                    # Initialize new record with zero durations
                    current_durations = {'off': 0, 'prep': 0, 'on': 0, 'unknown': 0}
                    previous_status = None
                    previous_start_time = None

                # Calculate and update durations if there was a previous status
                if previous_status and previous_start_time and is_working_hours():
                    duration = (current_time - previous_start_time).total_seconds()
                    duration_column = previous_status.lower()
                    current_durations[duration_column] += duration

                # Insert event into machine_events table
                cursor.execute(
                    """INSERT INTO machine_events 
                       (machine_id, timestamp, status) 
                       VALUES (?, ?, ?)""",
                    (machine_id, current_time.isoformat(), status)
                )
                
                # Update machine_runtime table
                cursor.execute("""
                    INSERT OR REPLACE INTO machine_runtime 
                    (machine_id, current_status, current_start_time,
                     off_duration, prep_duration, on_duration, unknown_duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    machine_id, 
                    status,
                    current_time.isoformat(),
                    current_durations['off'],
                    current_durations['prep'],
                    current_durations['on'],
                    current_durations['unknown']
                ))
                
                cursor.execute("COMMIT")
                conn.commit()
                logger.info(f"Status change logged for {machine_id}: {status}")
                return True
                
        except sqlite3.Error as e:
            attempts += 1
            if attempts == max_retries:
                logger.error(f"Failed to log status change after {max_retries} attempts: {e}")
                return False
            time.sleep(retry_delay)
            
    return False

def reset_daily_counters():
    """Reset the runtime counters at 6 AM daily"""
    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE machine_runtime 
                SET off_duration = 0,
                    prep_duration = 0,
                    on_duration = 0,
                    unknown_duration = 0
            """)
            conn.commit()
            logger.info("Daily counters reset successfully")
    except sqlite3.Error as e:
        logger.error(f"Error resetting daily counters: {e}")

def delete_old_data():
    """Delete data older than one month"""
    try:
        with closing(get_db_connection()) as conn:
            one_month_ago = datetime.now() - timedelta(days=30)
            cursor = conn.execute(
                "DELETE FROM machine_events WHERE timestamp < ?",
                (one_month_ago.isoformat(),)
            )
            conn.commit()
            logger.info(f"Deleted {cursor.rowcount} old records")
    except sqlite3.Error as e:
        logger.error(f"Error deleting old data: {e}")

def main():
    """Main data collection loop"""
    logger.info("Starting data collector service")
    
    try:
        setup_gpio()
        
        # Initial reset of counters if starting near 6 AM
        now = datetime.now()
        if now.hour == 6 and now.minute < 5:  # If starting between 6:00 and 6:05
            reset_daily_counters()

        last_reset_day = now.day
        last_cleanup_day = now.day
        
        while True:
            try:
                current_time = datetime.now()
                
                # Check for daily reset at 6 AM
                if current_time.hour == 6 and current_time.minute == 0 and current_time.day != last_reset_day:
                    reset_daily_counters()
                    last_reset_day = current_time.day
                
                # Check for daily cleanup at midnight
                if current_time.hour == 0 and current_time.minute == 0 and current_time.day != last_cleanup_day:
                    delete_old_data()
                    last_cleanup_day = current_time.day
                
                # Collect data during working hours
                if is_working_hours():
                    # GRS_14 uses inverted logic
                    condition = get_machine_condition(GRS_14Lamp, GRS_14Switch, invert=True)
                    log_status_change("GRS_14", condition)
                    
                    # Other machines use normal logic
                    for machine_id, lamp_pin, switch_pin in [
                        ("GRS_17", GRS_17Lamp, GRS_17Switch),
                        ("GRS_19", GRS_19Lamp, GRS_19Switch)
                    ]:
                        condition = get_machine_condition(lamp_pin, switch_pin)
                        log_status_change(machine_id, condition)
                
                time.sleep(COLLECTION_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(COLLECTION_INTERVAL)  # Continue despite errors
                
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        GPIO.cleanup()
        logger.info("Cleanup completed")

if __name__ == "__main__":
    main()
