// ===============================
// MODE SWITCH (LOGIN / SIGNUP)
// ===============================
function switchMode(mode) {
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const loginBtn = document.getElementById('tab-login');
    const signupBtn = document.getElementById('tab-signup');
    const errorMsgs = document.querySelectorAll('.error-msg');

    errorMsgs.forEach(msg => msg.innerText = "");

    if (mode === 'login') {
        loginForm.classList.remove('hidden');
        signupForm.classList.add('hidden');
        loginBtn.classList.add('active');
        signupBtn.classList.remove('active');
    } else {
        loginForm.classList.add('hidden');
        signupForm.classList.remove('hidden');
        loginBtn.classList.remove('active');
        signupBtn.classList.add('active');
    }
}

// ===============================
// TOGGLE PASSWORD VISIBILITY
// ===============================
function togglePassword(fieldId) {
    const input = document.getElementById(fieldId);
    input.type = input.type === "password" ? "text" : "password";
}

// ===============================
// LOGIN HANDLER (UPDATED)
// ===============================
async function handleLogin(event) {
    event.preventDefault();

    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-pass').value.trim();
    const errorEl = document.getElementById('login-error');
    const submitBtn = event.target.querySelector('button');

    // Validation
    if (!email || !password) {
        errorEl.innerText = "Please fill in all fields.";
        return;
    }

    // Loading state
    submitBtn.innerText = "Logging in...";
    submitBtn.disabled = true;
    errorEl.innerText = "";

    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (data.status === 'success') {

            // OPTIONAL: Store token/session (future-ready)
            if (data.token) {
                localStorage.setItem("authToken", data.token);
            }

            // ✅ REDIRECT TO INDOOR DASHBOARD (IMPORTANT CHANGE)
            window.location.href = "/indoor";

        } else {
            errorEl.innerText = data.message || "Invalid credentials.";
            submitBtn.innerText = "Log In";
            submitBtn.disabled = false;
        }

    } catch (err) {
        console.error("Login Error:", err);
        errorEl.innerText = "Server connection failed.";
        submitBtn.innerText = "Log In";
        submitBtn.disabled = false;
    }
}

// ===============================
// SIGNUP HANDLER (READY FOR BACKEND)
// ===============================
async function handleSignup(event) {
    event.preventDefault();

    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-pass').value;
    const confirm = document.getElementById('signup-confirm').value;
    const errorEl = document.getElementById('signup-error');
    const submitBtn = event.target.querySelector('button');

    // Validation
    if (!name || !email || !password || !confirm) {
        errorEl.innerText = "All fields are required.";
        return;
    }

    if (password !== confirm) {
        errorEl.innerText = "Passwords do not match!";
        return;
    }

    // Loading
    submitBtn.innerText = "Creating...";
    submitBtn.disabled = true;
    errorEl.innerText = "";

    try {
        const response = await fetch('/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password, confirmPassword: confirm })
        });

        const data = await response.json();

        if (data.status === 'success') {
            alert("Account created successfully! Please login.");
            switchMode('login');
        } else {
            errorEl.innerText = data.message || "Signup failed.";
        }

    } catch (err) {
        console.error("Signup Error:", err);
        errorEl.innerText = "Server error.";
    }

    submitBtn.innerText = "Create Account";
    submitBtn.disabled = false;
}

// ===============================
// AUTO LOGIN CHECK (OPTIONAL)
// ===============================
window.onload = function () {
    const token = localStorage.getItem("authToken");

    if (token && window.location.pathname === "/login") {
        // Already logged in → redirect
        window.location.href = "/indoor";
    }
};