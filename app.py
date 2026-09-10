from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from config import Config
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)
app.config.from_object(Config)

CATEGORIES = ['Electrician', 'Plumber', 'Carpenter', 'Home Cleaning', 'AC Repair', 'Painter', 'Mechanic', 'Other']

def get_db():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'], port=app.config['MYSQL_PORT'],
        user=app.config['MYSQL_USER'], password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DATABASE']
    )

def query(sql, params=(), fetchone=False, fetchall=False):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        if fetchone: return cur.fetchone()
        if fetchall: return cur.fetchall()
        conn.commit(); return cur.lastrowid
    finally:
        cur.close(); conn.close()

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

@app.route('/')
def home():
    try:
        providers = query('''SELECT p.id,p.category,p.address,p.experience_years,p.availability,p.verified,p.rating,u.name
                             FROM providers p JOIN users u ON u.id=p.user_id
                             ORDER BY p.verified DESC,p.rating DESC LIMIT 6''', fetchall=True)
    except Error:
        providers = []
    return render_template('index.html', providers=providers, categories=CATEGORIES)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name=request.form['name'].strip(); email=request.form['email'].strip().lower()
        password=request.form['password']; phone=request.form.get('phone','').strip(); role=request.form['role']
        if role not in ('customer','provider'): role='customer'
        try:
            user_id=query('INSERT INTO users(name,email,password,phone,role) VALUES(%s,%s,%s,%s,%s)',
                (name,email,generate_password_hash(password),phone,role))
            if role=='provider':
                category=request.form.get('category','Other')
                query('INSERT INTO providers(user_id,category,description,experience_years,address) VALUES(%s,%s,%s,%s,%s)',
                    (user_id,category,request.form.get('description',''),request.form.get('experience_years',0) or 0,request.form.get('address','')))
            flash('Registration successful. Please login.', 'success'); return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            flash('This email is already registered.', 'error')
        except Error as e:
            flash(f'Database error: {e}', 'error')
    return render_template('register.html', categories=CATEGORIES)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form['email'].strip().lower(); password=request.form['password']
        try:
            user=query('SELECT * FROM users WHERE email=%s',(email,),fetchone=True)
            if user and check_password_hash(user['password'],password):
                session.clear(); session['user_id']=user['id']; session['name']=user['name']; session['role']=user['role']
                return redirect(url_for('dashboard'))
            flash('Invalid email or password.', 'error')
        except Error as e: flash(f'Database error: {e}','error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); flash('Logged out successfully.','success'); return redirect(url_for('home'))

@app.route('/providers')
def providers():
    category=request.args.get('category',''); search=request.args.get('search','').strip()
    sql='''SELECT p.*,u.name,u.phone FROM providers p JOIN users u ON p.user_id=u.id WHERE 1=1'''; params=[]
    if category: sql+=' AND p.category=%s'; params.append(category)
    if search: sql+=' AND (u.name LIKE %s OR p.category LIKE %s OR p.address LIKE %s)'; params += [f'%{search}%']*3
    sql+=' ORDER BY p.verified DESC,p.rating DESC'
    try: rows=query(sql,tuple(params),fetchall=True)
    except Error as e: rows=[]; flash(f'Database error: {e}','error')
    return render_template('providers.html', providers=rows, categories=CATEGORIES, selected=category, search=search)

@app.route('/dashboard')
@login_required
def dashboard():
    if session['role']=='provider':
        provider=query('SELECT * FROM providers WHERE user_id=%s',(session['user_id'],),fetchone=True)
        bookings=[] if not provider else query('''SELECT b.*,u.name AS customer_name FROM bookings b JOIN users u ON b.customer_id=u.id WHERE b.provider_id=%s ORDER BY b.created_at DESC''',(provider['id'],),fetchall=True)
        return render_template('dashboard.html', provider=provider, bookings=bookings)
    bookings=query('''SELECT b.*,p.category,u.name AS provider_name FROM bookings b JOIN providers p ON b.provider_id=p.id JOIN users u ON p.user_id=u.id WHERE b.customer_id=%s ORDER BY b.created_at DESC''',(session['user_id'],),fetchall=True)
    return render_template('dashboard.html', bookings=bookings, provider=None)

@app.route('/book/<int:provider_id>', methods=['POST'])
@login_required
def book(provider_id):
    if session['role']!='customer': flash('Only customers can create bookings.','error'); return redirect(url_for('providers'))
    try:
        query('INSERT INTO bookings(customer_id,provider_id,service_date,message) VALUES(%s,%s,%s,%s)',
              (session['user_id'],provider_id,request.form['service_date'],request.form.get('message','')))
        flash('Booking request sent successfully!','success')
    except Error as e: flash(f'Booking failed: {e}','error')
    return redirect(url_for('dashboard'))

@app.route('/booking/<int:booking_id>/<status>', methods=['POST'])
@login_required
def booking_status(booking_id,status):
    if session['role']!='provider' or status not in ('Accepted','Completed','Cancelled'): return redirect(url_for('dashboard'))
    provider=query('SELECT id FROM providers WHERE user_id=%s',(session['user_id'],),fetchone=True)
    if provider: query('UPDATE bookings SET status=%s WHERE id=%s AND provider_id=%s',(status,booking_id,provider['id']))
    return redirect(url_for('dashboard'))

@app.route('/review/<int:provider_id>', methods=['POST'])
@login_required
def review(provider_id):
    if session['role']!='customer': return redirect(url_for('providers'))
    rating=max(1,min(5,int(request.form['rating']))); comment=request.form.get('comment','')
    query('INSERT INTO reviews(customer_id,provider_id,rating,comment) VALUES(%s,%s,%s,%s)',(session['user_id'],provider_id,rating,comment))
    avg=query('SELECT AVG(rating) AS avg_rating FROM reviews WHERE provider_id=%s',(provider_id,),fetchone=True)
    query('UPDATE providers SET rating=%s WHERE id=%s',(round(float(avg['avg_rating']),1),provider_id))
    flash('Review submitted. Thank you!','success'); return redirect(url_for('providers'))

@app.errorhandler(500)
def internal_error(e): return render_template('error.html', message='Something went wrong. Please check your database configuration.'),500

if __name__=='__main__': app.run(debug=True)
