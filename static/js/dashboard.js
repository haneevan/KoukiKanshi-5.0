// Machine state tracker
const machineStates = {};

const statusMap = {
    "ON": "加工中",
    "OFF": "停止",
    "PREP": "準備中",
    "UNKNOWN": "不明"
};

// Active timers tracking
let activeTimers = {};

// Server time offset and sync variables
let serverTimeOffset = 0;
let lastServerSync = 0;
let syncAccuracy = 1000;
let globalResetTime = null;
let globalStartTime = null;
let lastKnownServerTime = null;

// Get server time by adjusting local time with offset
function getAdjustedTime() {
    return new Date(Date.now() + serverTimeOffset);
}

// Get precise time from last known server time
function getPreciseServerTime() {
    if (!lastKnownServerTime) {
        return Math.floor((Date.now() + serverTimeOffset) / 1000) * 1000;
    }
    return Math.floor((Date.now() - lastServerSync + lastKnownServerTime) / 1000) * 1000;
}

// Initialize timeline blocks
function initTimelines() {
    const machines = ['GRS_14', 'GRS_17', 'GRS_19'];
    machines.forEach(machine => {
        const timeline = document.getElementById(`${machine}-timeline`);
        timeline.innerHTML = '';

        for (let i = 0; i < 144; i++) {
            const block = document.createElement('div');
            block.className = 'timeline-block block-inactive';
            block.dataset.interval = i;
            timeline.appendChild(block);
        }
    });
}

// Format time duration
function formatDuration(seconds) {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return '' + String(hrs).padStart(2, '0') + ':' + String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}

// Update timeline display
function updateTimeline(machineId, timelineData) {
    const timeline = document.getElementById(`${machineId}-timeline`);
    if (!timeline) return;

    const blocks = timeline.querySelectorAll('.timeline-block');
    if (!blocks || blocks.length === 0) {
        console.error(`No timeline blocks found for ${machineId}`);
        return;
    }

    const now = new Date();
    const currentHour = now.getHours();
    const currentMinute = now.getMinutes();

    // Reset only future blocks at the start of each day before 6 AM
    if (currentHour < 6) {
        blocks.forEach(block => {
            block.className = 'timeline-block block-inactive';
            block.style.opacity = '0.3';
        });
        return;
    }

    // Calculate current interval (number of 5-minute blocks since 6 AM)
    const currentInterval = Math.floor(((currentHour - 6) * 60 + currentMinute) / 5);

    // Get the current machine status
    const currentStatus = machineStates[machineId]?.currentState?.toLowerCase() || 'inactive';

    // Process each block up to the current time
    for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i];
        
        if (i <= currentInterval) {
            // Get the historical status for this block from timelineData
            const historicalStatus = timelineData[i] ? timelineData[i].toLowerCase() : 'inactive';
            
            // For past blocks (before current interval)
            if (i < currentInterval) {
                // Always use the historical status for past blocks
                block.className = `timeline-block block-${historicalStatus}`;
                block.style.opacity = '1';
            } 
            // For the current interval
            else if (i === currentInterval) {
                // Use current status for the current block
                block.className = `timeline-block block-${currentStatus} block-current`;
                block.style.opacity = '1';
            }
        } else {
            // Future blocks
            block.className = 'timeline-block block-inactive';
            block.style.opacity = '0.3';
        }
    }

    // Debug output
    console.log(`Timeline update for ${machineId}:`, timelineData.slice(0, currentInterval + 1));
}

// Add function to check working hours
function isWorkingHours() {
    const now = new Date();
    const startTime = new Date(now);
    const endTime = new Date(now);
    
    startTime.setHours(6, 0, 0, 0);
    endTime.setHours(18, 0, 0, 0);
    
    return now >= startTime && now <= endTime;
}

// New function to handle synchronized counter starts
function startSynchronizedCounter(machineId, element, baseSeconds, serverStartTime) {
    if (activeTimers[machineId]) {
        clearInterval(activeTimers[machineId].interval);
    }

    // Use the server's start time directly
    const syncedStartTime = Math.floor(serverStartTime / 1000) * 1000;
    console.log(`Starting counter for ${machineId} with base seconds: ${baseSeconds}, start time: ${new Date(syncedStartTime).toISOString()}`);
    
    activeTimers[machineId] = {
        element: element,
        baseSeconds: baseSeconds,
        startTime: syncedStartTime,
        lastUpdateTime: Date.now(),
        interval: setInterval(() => {
            if (!isWorkingHours()) {
                clearInterval(activeTimers[machineId].interval);
                delete activeTimers[machineId];
                element.classList.remove('active-server-tracked');
                return;
            }

            const now = getPreciseServerTime();
            const elapsedSeconds = Math.max(0, Math.floor((now - syncedStartTime) / 1000));
            
            element.textContent = formatDuration(baseSeconds + elapsedSeconds);

            // Request sync if too much time has passed since last update
            if (Date.now() - lastServerSync > 10000) {
                updateMachineConditions();
            }
        }, 1000)
    };
}

// Update displayed times with synchronized counting
function updateDisplayedTimes(machineId, totalDurations, serverStartTime) {
    const machineData = machineStates[machineId];
    
    ['Off', 'Prep', 'On'].forEach(stateName => {
        const element = document.getElementById(machineId + '-' + stateName.toLowerCase() + '-time');
        if (!element) return;

        const totalSeconds = totalDurations[stateName] || 0;
        element.textContent = formatDuration(totalSeconds);
        element.classList.remove('active-server-tracked');
        
        if (machineData.currentState?.toUpperCase() === stateName.toUpperCase() && isWorkingHours()) {
            element.classList.add('active-server-tracked');
            startSynchronizedCounter(machineId, element, totalSeconds, serverStartTime);
        }
    });
}

// Update machine current time display
function updateMachineCurrentTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('ja-JP', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });

    ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machine => {
        const element = document.getElementById(`${machine}-current-time`);
        if (element) {
            element.textContent = timeString;
        }
    });
}

// Update machine conditions from server
async function updateMachineConditions() {
    try {
        const requestStart = Date.now();
        const response = await fetch('/update_conditions');
        const responseTime = Date.now() - requestStart;
        
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();

        // Store server time information
        const serverTime = new Date(data.debug_info.current_time);
        lastKnownServerTime = serverTime.getTime();
        lastServerSync = Date.now();

        // Log timing information
        console.log('Time sync info:', {
            server_time: serverTime.toISOString(),
            client_time: new Date().toISOString(),
            response_time_ms: responseTime,
            last_sync_age_ms: Date.now() - lastServerSync
        });

        if (data.machine_conditions && data.total_durations && data.timeline_data) {
            // If this is a reset, clear all existing timers
            if (data.just_reset) {
                Object.keys(activeTimers).forEach(machine => {
                    if (activeTimers[machine]) {
                        clearInterval(activeTimers[machine].interval);
                        delete activeTimers[machine];
                    }
                });
                console.log('Reset detected, cleared all timers');
            }

            // Update each machine's state
            Object.entries(data.machine_conditions).forEach(([machine, condition]) => {
                const statusElement = document.querySelector(`#${machine}-card .machine-status`);
                if (statusElement) {
                    const japaneseStatus = statusMap[condition.toUpperCase()] || "不明";
                    statusElement.textContent = japaneseStatus;
                    statusElement.className = `machine-status status-${condition.toLowerCase()}`;
                }

                if (machineStates[machine]) {
                    const previousState = machineStates[machine].currentState;
                    machineStates[machine].currentState = condition;

                    if (previousState !== condition || !activeTimers[machine] || data.just_reset) {
                        updateDisplayedTimes(machine, data.total_durations[machine], lastKnownServerTime);
                    }
                }

                if (data.timeline_data && data.timeline_data[machine]) {
                    updateTimeline(machine, data.timeline_data[machine]);
                }
            });
        }
    } catch (error) {
        console.error('Error updating machine conditions:', error);
    }
}

// Update the main date and time display
function updateDateTimeDisplay() {
    const now = new Date();
    const dateOptions = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    };
    const timeOptions = {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    };

    const formattedDate = now.toLocaleDateString('ja-JP', dateOptions);
    const formattedTime = now.toLocaleTimeString('ja-JP', timeOptions);

    const dateElement = document.getElementById('current-date');
    const timeElement = document.getElementById('current-time');

    if (dateElement) {
        dateElement.textContent = `日付: ${formattedDate}`;
    }
    if (timeElement) {
        timeElement.textContent = `時間: ${formattedTime}`;
    }
}

// Initialize everything on load
document.addEventListener('DOMContentLoaded', () => {
    console.log("Initializing dashboard...");
    
    // Initialize machine states
    ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machine => {
        machineStates[machine] = {
            currentState: null
        };
    });

    // Initialize timelines and displays
    initTimelines();
    updateMachineCurrentTime();
    updateDateTimeDisplay();

    // Initial data fetch
    updateMachineConditions();

    // Set up periodic updates
    setInterval(updateMachineConditions, 5000);  // Update conditions every 5 seconds
    setInterval(updateMachineCurrentTime, 1000);  // Update machine time every second
    setInterval(updateDateTimeDisplay, 1000);     // Update main time display every second
});

// Clean up timers when the page is unloaded
window.addEventListener('beforeunload', () => {
    Object.values(activeTimers).forEach(timer => {
        if (timer.interval) {
            clearInterval(timer.interval);
        }
    });
});
