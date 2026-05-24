let currentAssignment = null;
let currentHospitalRecommendations = [];
let routeMap = null;
let routeMapState = {
    driverLocation: null,
    destinationLocation: null,
    routeLayer: null,
    driverMarker: null,
    destinationMarker: null
};

function resetRouteMap() {
    routeMapState = {
        driverLocation: null,
        destinationLocation: null,
        routeLayer: null,
        driverMarker: null,
        destinationMarker: null
    };

    if (routeMap) {
        routeMap.remove();
        routeMap = null;
    }
}

function buildMapsDirectionsUrl(locationName) {
    const destination = encodeURIComponent(locationName || '');
    return `https://www.google.com/maps/dir/?api=1&destination=${destination}`;
}

function renderRoutePanel() {
    const panel = document.getElementById('route-panel');
    if (!panel) return;

    if (!currentAssignment) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }

    const recommendedHospital = currentHospitalRecommendations[0];
    const routeTarget = currentAssignment.phase === 'to_hospital'
        ? (recommendedHospital ? recommendedHospital.location : currentAssignment.hospitalLocation)
        : currentAssignment.locationName;
    const routeUrl = buildMapsDirectionsUrl(routeTarget);
    const routeTitle = currentAssignment.phase === 'to_hospital' ? 'Route to hospital' : 'Route to accident spot';
    const routeLabel = currentAssignment.phase === 'to_hospital' ? 'Hospital destination' : 'Accident spot';
    const actionLabel = currentAssignment.phase === 'to_hospital' ? 'Reached hospital' : 'Reached accident spot';

    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="route-card">
            <h3>${routeTitle}</h3>
            <div class="route-summary">
                <p class="info-text"><strong>${routeLabel}:</strong> ${routeTarget || 'Not available'}</p>
                <p class="info-text"><strong>Recommended hospital:</strong> ${recommendedHospital ? recommendedHospital.name : 'Waiting for recommendation'}</p>
            </div>
            <div id="route-map" class="route-map">
                <div class="muted" style="padding:1.5rem">Loading route map...</div>
            </div>
            <div class="route-actions">
                <button class="btn btn-green" onclick="window.open('${routeUrl}', '_blank', 'noopener')">Open route</button>
                <button class="btn btn-red" onclick="markRouteReached()">${actionLabel}</button>
            </div>
        </div>
    `;
}

// PAGE SWITCHING LOGIC 
function switchRole(role) {
    // Hide all pages
    document.querySelectorAll('.page-section').forEach(page => {
        page.classList.remove('active');
    });

    // Show selected page
    const selectedPage = document.getElementById(role + '-page');
    if (selectedPage) {
        selectedPage.classList.add('active');
    }

    // Update role indicator
    const roleLabels = {
        'home': 'Home',
        'user': 'Reporter',
        'driver': 'Driver',
        'hospital': 'Hospital'
    };
    document.getElementById('current-role').textContent = roleLabels[role] || role;

    // Load data if needed
    if (role === 'driver') {
        loadAlerts();
    } else if (role === 'hospital') {
        loadHospitals();
    }

    // Close mobile menu
    const navMenu = document.getElementById('nav-menu');
    if (navMenu) {
        navMenu.classList.remove('active');
    }
}

// USER EMERGENCY REPORTING 
function validateEmergencyForm() {
    const name = document.getElementById('reporter-name').value.trim();
    const location = document.getElementById('location').value.trim();

    if (!name) {
        alert('Please enter your name');
        return false;
    }
    if (!location) {
        alert('Please enter the location of the emergency');
        return false;
    }
    if (name.length < 3) {
        alert('Name should be at least 3 characters long');
        return false;
    }
    if (location.length < 3) {
        alert('Location should be at least 3 characters long');
        return false;
    }
    return true;
}

async function submitEmergency() {
    if (!validateEmergencyForm()) return;

    const name = document.getElementById('reporter-name').value;
    const location = document.getElementById('location').value;
    const severity = document.getElementById('severity').value;
    const injury = document.getElementById('injury-type').value;

    try {
        const response = await fetch('/api/emergency', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                reporter_name: name,
                location_name: location,
                severity: severity,
                injury_type: injury
            })
        });

        const data = await response.json();

        if (data.success) {
            document.getElementById('step-form').style.display = 'none';
            document.getElementById('step-status').style.display = 'block';
            document.getElementById('emergency-id').textContent = data.emergency_id;
            document.getElementById('ambulance-info').textContent =
                    `Ambulance assigned: ${data.ambulance.driver_name} (${data.ambulance.vehicle_no})`;
        } else {
                alert((data.message || 'No ambulance available right now. Please call 102.'));
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error submitting emergency. Please try again.');
    }
}

// DRIVER DASHBOARD 
async function loadAlerts() {
    try {
        const response = await fetch('/api/alerts');
        const alerts = await response.json();
        const container = document.getElementById('alerts-list');

        if (!container) return;

        if (currentAssignment) {
            container.innerHTML = `
                <div class="alert-card active-case">
                    <div class="alert-title">
                        <strong>Active case in progress</strong>
                        <span class="badge badge-red">${currentAssignment.phase === 'to_hospital' ? 'To hospital' : 'En route'}</span>
                    </div>
                    <p class="alert-info"><strong>Accident spot:</strong> ${currentAssignment.locationName || 'Not available'}</p>
                    <p class="alert-info"><strong>Hospital:</strong> ${currentAssignment.hospitalLocation || (currentHospitalRecommendations[0] ? currentHospitalRecommendations[0].location : 'Pending')}</p>
                </div>
            `;
            return;
        }

        if (alerts.length === 0) {
            container.innerHTML = '<div class="muted">✓ No active alerts. All emergencies handled!</div>';
            return;
        }

        container.innerHTML = alerts.map(alert => {
            const severityColor = alert.severity === 'critical' ? 'red' : (alert.severity === 'moderate' ? 'yellow' : 'green');
            const severityLabel = alert.severity === 'critical' ? 'Critical' : (alert.severity === 'moderate' ? 'Moderate' : 'Mild');
            
            return `
                <div class="alert-card" data-emergency-id="${alert.id}" data-severity="${alert.severity}" data-injury="${alert.injury_type}" data-location="${alert.location_name}">
                    <div class="alert-title">
                        <strong>New Emergency</strong>
                        <span class="badge badge-${severityColor}">
                            ${severityLabel}
                        </span>
                    </div>
                    <p class="alert-info"><strong>Location:</strong> ${alert.location_name}</p>
                    <p class="alert-info"><strong>Injury:</strong> ${alert.injury_type}</p>
                    <p class="alert-info"><strong>Reported by:</strong> ${alert.reporter_name}</p>
                    <div class="alert-buttons">
                        <button class="btn btn-green accept-alert-btn">
                            Accept case
                        </button>
                        <button class="btn decline-alert-btn" style="border-color:#c41e3a;color:#8B0000">
                            Decline
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // Add event listeners using event delegation
        container.querySelectorAll('.accept-alert-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const alertCard = this.closest('.alert-card');
                const emergencyId = parseInt(alertCard.dataset.emergencyId);
                const severity = alertCard.dataset.severity;
                const injury = alertCard.dataset.injury;
                const locationName = alertCard.dataset.location || '';
                acceptAlert(emergencyId, severity, injury, locationName);
            });
        });

        container.querySelectorAll('.decline-alert-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                declineAlert();
            });
        });
    } catch (error) {
        console.error('Error loading alerts:', error);
        document.getElementById('alerts-list').innerHTML = '<div class="muted">Error loading alerts</div>';
    }
}

async function acceptAlert(emergencyId, severity, injuryType, locationName) {
    const ambulanceId = 1; // In production, this comes from logged-in driver

    try {
        // Disable button and show loading state
        const buttons = document.querySelectorAll('.accept-alert-btn');
        buttons.forEach(btn => btn.disabled = true);

        const response = await fetch(`/api/accept/${emergencyId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ambulance_id: ambulanceId })
        });

        if (!response.ok) {
            throw new Error('Failed to accept alert');
        }

        const data = await response.json();

        currentAssignment = {
            emergencyId,
            severity,
            injuryType,
            locationName: data.location_name || locationName || 'Unknown location',
            hospitalLocation: data.assigned_hospital ? data.assigned_hospital.location : '',
            phase: 'to_scene'
        };

        currentHospitalRecommendations = Array.isArray(data.hospital_recommendations) ? data.hospital_recommendations : [];

        // Hide other requests and show the active route only
        document.getElementById('hospital-suggestions').style.display = 'none';
        await loadHospitalSuggestions(severity, injuryType);
        renderRoutePanel();
        await initializeRouteMap(currentAssignment.locationName);
        
        // Update driver status
        document.getElementById('driver-status').textContent = 'On scene';
        document.getElementById('driver-status').className = 'badge badge-red';

        // Remove accepted alert from list
        const alertCards = document.querySelectorAll('.alert-card');
        alertCards.forEach(card => {
            if (parseInt(card.dataset.emergencyId) === emergencyId) {
                card.style.opacity = '0.5';
            } else {
                card.remove();
            }
        });

        const alertsList = document.getElementById('alerts-list');
        if (alertsList) {
            alertsList.insertAdjacentHTML('beforeend', '<div class="muted" style="padding-top:0">Other requests are hidden until the active case is completed.</div>');
        }

        // Re-enable buttons
        buttons.forEach(btn => btn.disabled = false);

    } catch (error) {
        console.error('Error accepting alert:', error);
        alert('Error accepting alert. Please try again.');
        
        // Re-enable buttons on error
        const buttons = document.querySelectorAll('.accept-alert-btn');
        buttons.forEach(btn => btn.disabled = false);
    }
}

function declineAlert() {
    alert('Alert will be offered to the next available driver.');
}

async function loadHospitalSuggestions(severity, injuryType) {
    try {
        const response = await fetch('/api/suggest-hospital', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ severity: severity, injury_type: injuryType })
        });

        const hospitals = await response.json();
        const container = document.getElementById('hospitals-list');

        if (!hospitals || hospitals.length === 0) {
            container.innerHTML = '<div class="muted">No hospitals available</div>';
            currentHospitalRecommendations = [];
            renderRoutePanel();
            return;
        }

        currentHospitalRecommendations = hospitals;

        container.innerHTML = hospitals.map((h, index) => `
            <div class="hospital-card ${index === 0 ? 'best' : ''}">
                ${index === 0 ? '<span class="badge badge-green" style="margin-bottom:10px;display:inline-block">Best match</span>' : ''}
                <div class="hospital-name">${h.name}</div>
                <div class="hospital-info">
                    <strong>${h.location}</strong>
                </div>
                <div class="hospital-info" style="margin-top:10px">
                    <strong>${h.available_beds}</strong> beds available &nbsp;|&nbsp;
                    <strong>${h.icu_available}</strong> ICU beds &nbsp;|&nbsp;
                    <strong>${h.doctors_available}</strong> doctors
                </div>
                <div class="hospital-info" style="margin-top:10px;padding:10px;background:#f8f9fa;border-radius:6px;">
                    ${h.has_trauma ? 'Trauma bay available' : 'No trauma bay'} &nbsp;
                    ${h.has_neurosurgeon ? 'Neurosurgeon available' : 'No neurosurgeon'}<br/>
                    ${h.has_burn_unit ? 'Burn unit available' : 'No burn unit'} &nbsp;
                    ${h.has_blood_bank ? 'Blood bank available' : 'No blood bank'}
                </div>
            </div>
        `).join('');

        renderRoutePanel();
    } catch (error) {
        console.error('Error loading hospitals:', error);
        document.getElementById('hospitals-list').innerHTML = '<div class="muted">Error loading hospital suggestions</div>';
    }
}

async function markRouteReached() {
    if (!currentAssignment) {
        return;
    }

    if (currentAssignment.phase === 'to_scene') {
        currentAssignment.phase = 'to_hospital';
        renderRoutePanel();
        await initializeRouteMap(currentHospitalRecommendations[0] ? currentHospitalRecommendations[0].location : currentAssignment.hospitalLocation);
        document.getElementById('driver-status').textContent = 'Transporting patient';
        document.getElementById('driver-status').className = 'badge badge-yellow';
        return;
    }

    try {
        const response = await fetch(`/api/reach-hospital/${currentAssignment.emergencyId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();
        if (!result.success) {
            throw new Error(result.message || 'Unable to complete case');
        }

        currentAssignment = null;
        currentHospitalRecommendations = [];
        resetRouteMap();
        renderRoutePanel();
        document.getElementById('hospital-suggestions').style.display = 'none';
        document.getElementById('driver-status').textContent = 'Available';
        document.getElementById('driver-status').className = 'badge badge-green';
        loadAlerts();
    } catch (error) {
        console.error('Error completing case:', error);
        alert('Unable to mark the case as reached. Please try again.');
    }
}

async function geocodeLocation(locationName) {
    const query = encodeURIComponent(locationName);
    const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${query}`, {
        headers: {
            'Accept': 'application/json'
        }
    });

    if (!response.ok) {
        throw new Error('Unable to geocode location');
    }

    const results = await response.json();
    if (!results || results.length === 0) {
        throw new Error('Location not found');
    }

    return {
        lat: parseFloat(results[0].lat),
        lng: parseFloat(results[0].lon),
        label: results[0].display_name || locationName
    };
}

function getDriverLocation() {
    return new Promise(resolve => {
        if (!navigator.geolocation) {
            resolve(null);
            return;
        }

        navigator.geolocation.getCurrentPosition(
            position => {
                resolve({
                    lat: position.coords.latitude,
                    lng: position.coords.longitude,
                    label: 'Current location'
                });
            },
            () => resolve(null),
            { enableHighAccuracy: true, timeout: 7000, maximumAge: 10000 }
        );
    });
}

async function initializeRouteMap(locationName) {
    const mapContainer = document.getElementById('route-map');
    if (!mapContainer || typeof L === 'undefined') {
        return;
    }

    mapContainer.innerHTML = '<div class="muted" style="padding:1.5rem">Loading route map...</div>';

    try {
        const destination = await geocodeLocation(locationName);
        const driverLocation = await getDriverLocation();

        routeMapState.destinationLocation = destination;
        routeMapState.driverLocation = driverLocation;

        mapContainer.innerHTML = '';
        if (routeMap) {
            routeMap.remove();
        }

        routeMap = L.map('route-map', {
            zoomControl: true,
            scrollWheelZoom: false
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(routeMap);

        routeMapState.destinationMarker = L.marker([destination.lat, destination.lng])
            .addTo(routeMap)
            .bindPopup(currentAssignment.phase === 'to_hospital'
                ? `Hospital: ${currentHospitalRecommendations[0] ? currentHospitalRecommendations[0].name : 'Destination'}`
                : `Accident spot: ${currentAssignment.locationName}`)
            .openPopup();

        const points = [];
        points.push([destination.lat, destination.lng]);

        if (driverLocation) {
            routeMapState.driverMarker = L.marker([driverLocation.lat, driverLocation.lng], {
                title: 'Ambulance location'
            }).addTo(routeMap).bindPopup('Ambulance current location');
            points.push([driverLocation.lat, driverLocation.lng]);

            try {
                const routeResponse = await fetch(`https://router.project-osrm.org/route/v1/driving/${driverLocation.lng},${driverLocation.lat};${destination.lng},${destination.lat}?overview=full&geometries=geojson`);
                if (routeResponse.ok) {
                    const routeData = await routeResponse.json();
                    const route = routeData.routes && routeData.routes[0];
                    if (route && route.geometry) {
                        routeMapState.routeLayer = L.geoJSON(route.geometry, {
                            style: {
                                color: '#8B0000',
                                weight: 5,
                                opacity: 0.9
                            }
                        }).addTo(routeMap);
                    }
                }
            } catch (routeError) {
                console.error('Route fetch failed:', routeError);
            }
        }

        if (points.length === 1) {
            routeMap.setView(points[0], 14);
        } else {
            routeMap.fitBounds(L.latLngBounds(points).pad(0.2));
        }
    } catch (error) {
        console.error('Error loading route map:', error);
        mapContainer.innerHTML = '<div class="muted" style="padding:1.5rem">Map preview unavailable. Open the route for directions.</div>';
    }
}

//  HOSPITAL MANAGEMENT 
async function loadHospitals() {
    try {
        const response = await fetch('/api/hospitals');
        const hospitals = await response.json();
        const select = document.getElementById('hospital-select');
        if (!select) return;

        // Clear existing options (keep the placeholder)
        select.innerHTML = '<option value="">-- Select Your Hospital --</option>';

        hospitals.forEach(h => {
            const option = document.createElement('option');
            option.value = h.id;
            option.textContent = h.name;
            option.dataset.info = JSON.stringify(h);
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading hospitals:', error);
    }
}

function loadHospitalData() {
    const select = document.getElementById('hospital-select');
    const selected = select.options[select.selectedIndex];
    if (!selected.value || !selected.dataset.info) return;

    const h = JSON.parse(selected.dataset.info);
    document.getElementById('inp-beds').value = h.available_beds;
    document.getElementById('inp-icu').value = h.icu_available;
    document.getElementById('inp-docs').value = h.doctors_available;
    document.getElementById('chk-trauma').checked = h.has_trauma;
    document.getElementById('chk-neuro').checked = h.has_neurosurgeon;
    document.getElementById('chk-burn').checked = h.has_burn_unit;
    document.getElementById('chk-blood').checked = h.has_blood_bank;
}

function validateHospitalForm() {
    const hospitalId = document.getElementById('hospital-select').value;
    if (!hospitalId) { 
        alert('Please select a hospital');
        return false;
    }

    const beds = parseInt(document.getElementById('inp-beds').value);
    const icu = parseInt(document.getElementById('inp-icu').value);
    const docs = parseInt(document.getElementById('inp-docs').value);

    if (isNaN(beds) || beds < 0) {
        alert('Please enter a valid number of beds');
        return false;
    }
    if (isNaN(icu) || icu < 0) {
        alert('Please enter a valid number of ICU beds');
        return false;
    }
    if (isNaN(docs) || docs < 0) {
        alert('Please enter a valid number of doctors');
        return false;
    }

    return true;
}

async function saveHospital() {
    if (!validateHospitalForm()) return;

    const hospitalId = document.getElementById('hospital-select').value;
    const data = {
        hospital_id: parseInt(hospitalId),
        available_beds: parseInt(document.getElementById('inp-beds').value) || 0,
        icu_available: parseInt(document.getElementById('inp-icu').value) || 0,
        doctors_available: parseInt(document.getElementById('inp-docs').value) || 0,
        has_trauma: document.getElementById('chk-trauma').checked,
        has_neurosurgeon: document.getElementById('chk-neuro').checked,
        has_burn_unit: document.getElementById('chk-burn').checked,
        has_blood_bank: document.getElementById('chk-blood').checked
    };

    try {
        const response = await fetch('/api/hospital/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const result = await response.json();
        if (result.success) {
            const msg = document.getElementById('save-msg');
            msg.style.display = 'block';
            setTimeout(() => { msg.style.display = 'none'; }, 3000);
        } else {
            alert('Error updating hospital');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error saving hospital data');
    }
}

//  INITIALIZE ON PAGE LOAD 
document.addEventListener('DOMContentLoaded', function() {
    // Show home page by default
    switchRole('home');

    // Setup mobile menu toggle
    const menuToggle = document.getElementById('menu-toggle');
    const navMenu = document.getElementById('nav-menu');
    if (menuToggle && navMenu) {
        menuToggle.addEventListener('click', function() {
            navMenu.classList.toggle('active');
        });
    }

    // Auto-refresh driver alerts every 10 seconds
    setInterval(function() {
        if (document.getElementById('driver-page').classList.contains('active')) {
            loadAlerts();
        }
    }, 10000);
});