// static/js/history.js

// Initialize timeline blocks
function initTimelines() {
    const machines = ['GRS_14', 'GRS_17', 'GRS_19'];
    machines.forEach(machine => {
        const timeline = document.getElementById(`${machine}-timeline`);
        if (!timeline) return;
        timeline.innerHTML = '';

        // Create blocks (144 blocks for 12 hours, 5 minutes each)
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
    return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// Update timeline display
function updateTimeline(machineId, machineData) {
    const timeline = document.getElementById(`${machineId}-timeline`);
    if (!timeline) return;

    const blocks = timeline.querySelectorAll('.timeline-block');
    if (!blocks || blocks.length === 0) return;

    // Reset all blocks
    blocks.forEach(block => {
        block.className = 'timeline-block block-inactive';
        block.style.opacity = '0.3';
    });

    if (!machineData || !machineData.events || machineData.events.length === 0) return;

    const events = machineData.events;
    const durations = machineData.durations;

    // Update duration displays first
    document.getElementById(`${machineId}-off-time`).textContent = formatDuration(Math.floor(durations.Off));
    document.getElementById(`${machineId}-prep-time`).textContent = formatDuration(Math.floor(durations.Prep));
    document.getElementById(`${machineId}-on-time`).textContent = formatDuration(Math.floor(durations.On));

    // Process timeline blocks
    let currentStatus = events[0].status.toLowerCase();
    let currentBlock = 0;

    events.forEach((event, index) => {
        const eventTime = new Date(event.timestamp);
        const blockIndex = Math.floor(((eventTime.getHours() - 6) * 60 + eventTime.getMinutes()) / 5);
        
        // Fill all blocks up to this event with the current status
        while (currentBlock < blockIndex && currentBlock < blocks.length) {
            blocks[currentBlock].className = `timeline-block block-${currentStatus}`;
            blocks[currentBlock].style.opacity = '1';
            currentBlock++;
        }
        
        currentStatus = event.status.toLowerCase();
    });

    // Fill remaining blocks with the last known status
    while (currentBlock < blocks.length) {
        blocks[currentBlock].className = `timeline-block block-${currentStatus}`;
        blocks[currentBlock].style.opacity = '1';
        currentBlock++;
    }
}

// Fetch and display history data for a specific date
async function fetchHistoryData(date) {
    try {
        const response = await fetch(`/api/history/data/${date}`);
        if (!response.ok) {
            throw new Error('Failed to fetch history data');
        }
        const data = await response.json();
        
        // Update each machine's timeline
        for (const [machineId, machineData] of Object.entries(data)) {
            updateTimeline(machineId, machineData);
        }
    } catch (error) {
        console.error('Error fetching history data:', error);
    }
}

// Get yesterday's date in YYYY-MM-DD format
function getYesterday() {
    const date = new Date();
    date.setDate(date.getDate() - 1);
    return date.toISOString().split('T')[0];
}

// Check if it's time to refresh (at 6 PM)
function shouldRefreshHistory() {
    const now = new Date();
    return now.getHours() === 18 && now.getMinutes() === 0;
}

// Schedule next refresh
function scheduleNextRefresh() {
    const now = new Date();
    const target = new Date(now);
    target.setHours(18, 0, 0, 0); // Set to 6 PM
    
    if (now >= target) {
        // If it's past 6 PM, schedule for tomorrow
        target.setDate(target.getDate() + 1);
    }
    
    const msUntilRefresh = target - now;
    return setTimeout(() => {
        // Refresh the page at exactly 6 PM
        window.location.reload();
    }, msUntilRefresh);
}

// Initialize everything on load
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize timelines with empty data
    initTimelines();
    ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machineId => {
        updateTimeline(machineId, []);
    });

    // Initialize date picker
    const datePicker = flatpickr("#date-picker", {
        dateFormat: "Y-m-d",
        maxDate: "yesterday",
        defaultDate: getYesterday(), // Set default to yesterday instead of today
        onChange: function(selectedDates) {
            if (selectedDates.length > 0) {
                const selectedDate = selectedDates[0];
                const formattedDate = selectedDate.toISOString().split('T')[0];
                const today = new Date().toISOString().split('T')[0];
                
                if (formattedDate === today) {
                    // If somehow today is selected, show empty data
                    ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machineId => {
                        updateTimeline(machineId, []);
                    });
                } else {
                    fetchHistoryData(formattedDate);
                }
            }
        }
    });

    // Initialize date and time display
    function updateDateTime() {
        const now = new Date();
        const dateOptions = { year: 'numeric', month: '2-digit', day: '2-digit' };
        const timeOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };

        document.getElementById('current-date').textContent = `日付: ${now.toLocaleDateString('ja-JP', dateOptions)}`;
        document.getElementById('current-time').textContent = `時間: ${now.toLocaleTimeString('ja-JP', timeOptions)}`;
    }

    updateDateTime();
    setInterval(updateDateTime, 1000);

    // Schedule refresh at 6 PM
    scheduleNextRefresh();

    // Fetch available dates and initialize calendar
    try {
        const response = await fetch('/api/history/dates');
        if (!response.ok) {
            throw new Error('Failed to fetch available dates');
        }
        const data = await response.json();
        
        if (data.dates && data.dates.length > 0) {
            // Enable only dates that have data
            datePicker.set('enable', data.dates);
            
            // If the current selected date is today, show empty data
            const selectedDate = datePicker.selectedDates[0];
            const today = new Date().toISOString().split('T')[0];
            
            if (selectedDate && selectedDate.toISOString().split('T')[0] === today) {
                ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machineId => {
                    updateTimeline(machineId, []);
                });
            } else {
                // Load most recent available date
                fetchHistoryData(data.dates[0]);
            }
        } else {
            // If no historical data available, show empty timelines
            ['GRS_14', 'GRS_17', 'GRS_19'].forEach(machineId => {
                updateTimeline(machineId, []);
            });
        }
    } catch (error) {
        console.error('Error fetching available dates:', error);
    }
});
