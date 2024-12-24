from flask import Flask, render_template, redirect, url_for, request, flash, session, send_from_directory
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime
import pickle
import spacy

app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the uploads folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load the trained model and vectorizer
model = pickle.load(open('model.pkl', 'rb'))
vectorizer = pickle.load(open('vectorizer.pkl', 'rb'))
nlp = spacy.load('en_core_web_sm')

def preprocess_text(text):
    doc = nlp(text.lower())
    tokens = [token.lemma_ for token in doc if not token.is_stop and not token.is_punct]
    return ' '.join(tokens)

# Database setup
def init_db():
    with sqlite3.connect("requests.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            description TEXT,
            status TEXT DEFAULT 'Pending',
            file_path TEXT,
            created_at TEXT
        )''')
    with sqlite3.connect("requests.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )''')

init_db()

@app.route('/')
def index():
    """Landing page with navigation options."""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect("requests.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, role FROM users WHERE username=? AND password=?", (username, password))
            user = cur.fetchone()
            if user:
                session['user_id'] = user[0]
                session['role'] = user[1]
                if user[1] == 'employee':
                    return redirect(url_for('employee_dashboard'))
                elif user[1] == 'manager':
                    return redirect(url_for('manager_dashboard'))
                elif user[1] == 'hr':
                    return redirect(url_for('hr_dashboard'))
            else:
                flash('Invalid credentials, please try again.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        with sqlite3.connect("requests.db") as conn:
            try:
                conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
                conn.commit()
                flash('Registration successful! Please log in.')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('Username already exists. Please choose a different username.')
    return render_template('register.html')

@app.route('/employee_dashboard')
def employee_dashboard():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM requests WHERE user_id=? AND status='Pending'", (session.get('user_id'),))
        requests = cur.fetchall()
    return render_template('employee_dashboard.html', requests=requests)

@app.route('/create_request_page')
def create_request_page():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    return render_template('create_request.html')

@app.route('/my_requests_page')
def my_requests_page():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM requests WHERE user_id=? ORDER BY created_at DESC", (session.get('user_id'),))
        requests = cur.fetchall()
    return render_template('my_requests.html', requests=requests)

@app.route('/manager_dashboard')
def manager_dashboard():
    if session.get('role') != 'manager':
        return redirect(url_for('login'))
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM requests WHERE status='Pending' OR status='Forwarded to Manager'")
        requests = cur.fetchall()
    return render_template('manager_dashboard.html', requests=requests)

@app.route('/hr_dashboard')
def hr_dashboard():
    if session.get('role') != 'hr':
        return redirect(url_for('login'))
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM requests WHERE status='Forwarded to HR'")
        requests = cur.fetchall()
        cur.execute("SELECT id, username, role FROM users")
        users = cur.fetchall()
    return render_template('hr_dashboard.html', requests=requests, users=users)

@app.route('/hr_registered_users')
def hr_registered_users():
    if session.get('role') != 'hr':
        return redirect(url_for('login'))
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users")
        users = cur.fetchall()
    return render_template('hr_registered_users.html', users=users)

@app.route('/create_request', methods=['POST'])
def create_request():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    title = request.form['title']
    description = request.form['description']
    file = request.files.get('file')
    file_path = None

    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Preprocess the description
    processed_description = preprocess_text(description)
    # Extract features
    features = vectorizer.transform([processed_description])
    # Predict risk level
    risk_level = model.predict(features)[0]

    # Determine action based on risk level
    if risk_level == 'low':
        status = 'Approved'
    elif risk_level == 'medium':
        status = 'Forwarded to Manager'
    elif risk_level == 'high':
        status = 'Forwarded to HR'
    else:
        status = 'Forwarded to Manager'

    with sqlite3.connect("requests.db") as conn:
        conn.execute(
            "INSERT INTO requests (user_id, title, description, file_path, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (session.get('user_id'), title, description, file_path, created_at, status)
        )
        conn.commit()

    flash('Request submitted successfully!')
    return redirect(url_for('my_requests_page'))

@app.route('/cancel_request', methods=['POST'])
def cancel_request():
    """Allows employees to cancel their request if it is still in 'Pending' state."""
    if session.get('role') != 'employee':
        return redirect(url_for('login'))

    request_id = request.form['request_id']
    with sqlite3.connect("requests.db") as conn:
        cur = conn.cursor()
        # Only cancel if the status is 'Pending'
        cur.execute("UPDATE requests SET status='Cancelled' WHERE id=? AND status='Pending' AND user_id=?", 
                    (request_id, session.get('user_id')))
        conn.commit()
    flash('Request canceled successfully!')
    return redirect(url_for('my_requests_page'))

@app.route('/update_request', methods=['POST'])
def update_request():
    request_id = request.form['request_id']
    status = request.form['status'].capitalize()
    with sqlite3.connect("requests.db") as conn:
        conn.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
        conn.commit()
    flash('Request status updated successfully!')
    return redirect(request.referrer)

@app.route('/remove_user', methods=['POST'])
def remove_user():
    user_id = request.form['user_id']
    with sqlite3.connect("requests.db") as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash('User removed successfully!')
    return redirect(url_for('hr_registered_users'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
