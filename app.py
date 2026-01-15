from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify, Response
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import re
from dotenv import load_dotenv
from pymongo import ASCENDING
import pymongo
from urllib.parse import urlparse
import razorpay
from bson.objectid import ObjectId
import os
from datetime import datetime
import math
import json

# Load env variables
load_dotenv()

# Get the absolute path for templates
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templets'))
app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# Razorpay Setup
# Razorpay Setup
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_live_S48A3olQrEUfFd")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "zx7XbZA6S3QGw9N26hRWh2BK")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# MongoDB connection
mongo_uri = os.getenv("MONGO_URI")
db = None

def ensure_db_connection():
    global db
    if db is not None: return db
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        try:
            db = client.get_default_database()
        except:
            parsed = urlparse(mongo_uri)
            dbname = parsed.path.lstrip('/') or 'KropKart'
            db = client[dbname]
        client.admin.command('ping')
        return db
    except Exception as e:
        print(f"DB Error: {e}")
        return None

def init_db():
    db_local = ensure_db_connection()
    if db_local is not None:
        collections = ["users", "products", "orders", "categories", "shipments", "admin"]
        for collection in collections:
            if collection not in db_local.list_collection_names():
                db_local.create_collection(collection)
        db_local.users.create_index([("email", ASCENDING)], unique=True)
        return True
    return False

# AI Analysis Logic
def analyze_quality(name, description, category, price):
    score = 0.5
    text = f"{name} {description} {category}".lower()
    if 'organic' in text: score += 0.2
    if 'premium' in text or 'pure' in text: score += 0.15
    if 'grade a' in text: score += 0.1
    return min(1.0, score)

def compute_adjusted_price(base_price, quality_score):
    gov_rate = 0.05
    bonus = 0.05 if quality_score > 0.8 else 0.02 if quality_score > 0.5 else 0
    return round(float(base_price) * (1 + gov_rate + bonus), 2)

@app.route('/statics/<path:filename>')
def serve_statics(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'statics'), filename)

@app.route("/")
def index():
    db_local = ensure_db_connection()
    products = list(db_local.products.find().sort("created_at", -1))  # Latest products first
    return render_template("index.html", products=products)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user_type = request.form.get("user_type", "citizen")
        
        db_local = ensure_db_connection()
        if db_local.users.find_one({"email": email}):
            flash("User already exists!", "error")
            return redirect("/register")
            
        db_local.users.insert_one({
            "name": name, "email": email, "password": generate_password_hash(password),
            "user_type": user_type, "created_at": datetime.now(), "wallet": 0
        })
        flash("Registration successful!", "success")
        return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db_local = ensure_db_connection()
        user = db_local.users.find_one({"email": email})
        if user and check_password_hash(user["password"], password):
            session.update({"user": user["email"], "name": user["name"], "user_type": user["user_type"]})
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect("/")  # Redirect to home page
        flash("Invalid credentials", "error")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect("/login")
    utype = session.get("user_type")
    if utype == "admin": return redirect("/admin")
    if utype == "farmer": return redirect("/landing")
    if utype == "business": return redirect("/landingb")
    return redirect("/citizen")

# ROLE-BASED PRODUCT LISTINGS
@app.route("/landing") # Farmer Landing
def landing():
    db_local = ensure_db_connection()
    # Farmers see their own products and can add more
    products = list(db_local.products.find({"owner": session.get("user")}))
    return render_template("landing.html", products=products)

@app.route("/landingb") # Business Landing/Control Panel
def landingb():
    db_local = ensure_db_connection()
    # Business page should show ALL products available for bulk sourcing (Farmers + Other Businesses)
    # The previous logic limited it to only farmers. Expanding to all listings.
    products = list(db_local.products.find())
    return render_template("landingb.html", products=products)

@app.route("/citizen") # Citizen Landing
def citizen():
    db_local = ensure_db_connection()
    # Normal people see ALL products
    products = list(db_local.products.find())
    return render_template("citizen.html", products=products)

@app.route("/add-listing")
def add_listing_page():
    if "user" not in session: return redirect("/login")
    if session.get("user_type") not in ["farmer", "business", "admin"]:
        flash("Unauthorized access!", "error")
        return redirect("/dashboard")
    return render_template("add_product.html")

@app.route("/add_product", methods=["POST"])
def add_product():
    if "user" not in session: return redirect("/login")
    if session.get("user_type") not in ["farmer", "business", "admin"]:
        flash("Only farmers and businesses can list products!", "error")
        return redirect("/dashboard")
    
    name = request.form.get("name")
    price = request.form.get("price")
    category = request.form.get("category")
    desc = request.form.get("description")
    
    # Handle image upload
    file = request.files.get("image")
    image_url = ""
    if file and file.filename:
        fname = secure_filename(file.filename)
        # Ensure image directory exists
        image_dir = os.path.join(os.path.dirname(__file__), 'statics', 'image')
        os.makedirs(image_dir, exist_ok=True)
        
        path = os.path.join(image_dir, fname)
        file.save(path)
        image_url = f"/statics/image/{fname}"
        print(f"Image saved to: {path}")

    quality = analyze_quality(name, desc, category, price)
    adj_price = compute_adjusted_price(price, quality)

    ensure_db_connection().products.insert_one({
        "name": name, "price": float(price), "adjusted_price": adj_price,
        "category": category, "description": desc, "image": image_url,
        "owner": session.get("user"), "owner_type": session.get("user_type"),
        "quality_score": quality, "created_at": datetime.now()
    })
    flash("Product listed with AI Quality Score!", "success")
    return redirect("/dashboard")

# Context Processor
@app.context_processor
def inject_razorpay_key():
    return dict(RAZORPAY_KEY_ID=RAZORPAY_KEY_ID)

@app.route("/checkout/<product_id>")
def checkout(product_id):
    if "user" not in session: return redirect("/login")
    db_local = ensure_db_connection()
    product = db_local.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        flash("Product not found!", "error")
        return redirect("/dashboard")
    return render_template("checkout.html", product=product)

# PAYMENT INTEGRATION
@app.route("/create_order", methods=["POST"])
def create_order():
    try:
        data = request.get_json()
        if not data or 'amount' not in data:
            return jsonify({"error": "Amount is required"}), 400
        
        amount = int(float(data['amount']) * 100)  # Convert to paise
        
        # Create Razorpay order
        order = razorpay_client.order.create({
            "amount": amount, 
            "currency": "INR", 
            "payment_capture": "1"
        })
        
        print(f"Order created successfully: {order['id']}")
        return jsonify(order)
    except Exception as e:
        print(f"Error creating order: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "failed", "message": "No data received"}), 400
        
        # Verify payment signature
        razorpay_client.utility.verify_payment_signature(data)
        
        # Record order in DB
        ensure_db_connection().orders.insert_one({
            "user": session.get("user"), 
            "product_id": data.get('product_id'),
            "amount": data.get('amount'), 
            "status": "paid", 
            "razorpay_payment_id": data.get('razorpay_payment_id'),
            "date": datetime.now()
        })
        
        print(f"Payment verified: {data.get('razorpay_payment_id')}")
        return jsonify({"status": "success"})
    except razorpay.errors.SignatureVerificationError as e:
        print(f"Signature verification failed: {str(e)}")
        return jsonify({"status": "failed", "message": "Invalid signature"}), 400
    except Exception as e:
        print(f"Payment verification error: {str(e)}")
        return jsonify({"status": "failed", "message": str(e)}), 500

# Webhook Setup
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "Saikiran9493@#")

@app.route("/webhook", methods=["POST"])
def webhook():
    # Verify the signature
    signature = request.headers.get('X-Razorpay-Signature')
    body = request.get_data().decode('utf-8')

    try:
        razorpay_client.utility.verify_webhook_signature(body, signature, RAZORPAY_WEBHOOK_SECRET)
        
        # Process the event
        event = request.json
        if event['event'] == 'payment.captured':
            payment = event['payload']['payment']['entity']
            # Here you can update order status in DB if needed (server-to-server confirmation)
            # db_local.orders.update_one(...)
            print(f"Payment Captured: {payment['id']}")
            
        return jsonify({"status": "ok"}), 200
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"status": "error", "message": "Invalid Signature"}), 400
    except Exception as e:
        print(e)
        return jsonify({"status": "error"}), 500

# AI CHATBOT API
@app.route("/api/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").lower()
    
    # Enhanced Knowledge Base
    responses = {
        "price": "Current market prices (per quintal):<br>• Rice: ₹2,200<br>• Wheat: ₹2,125<br>• Cotton: ₹6,080<br>Check the 'Live Market' section for more.",
        "paddy": "Paddy (Rice) is currently trending at ₹2,200/quintal. Best time to sell is late November.",
        "wheat": "Wheat prices are stable at ₹2,125. Demand is high in North India.",
        "organic": "Organic certification can increase your produce value by 20-30%. We prioritize organic listings!",
        "buy": "<b>To Buy:</b><br>1. Go to Marketplace<br>2. Select products<br>3. Click 'Buy Now' to pay securely via Razorpay.",
        "sell": "<b>To Sell:</b><br>1. Login as Farmer/Business<br>2. Go to Dashboard<br>3. Click 'List Product' or use the 'List Inventory' button.",
        "quality": "Our AI Quality Score considers:<br>• Visual freshness (via image)<br>• Product description<br>• Standard grade specifications.",
        "subsidy": "Govt subsidies available for:<br>• Drip Irrigation (50%)<br>• Solar Pumps (pm-KUSUM)<br>• Organic Fertilizer.",
        "weather": "It looks sunny across major farming belts. Good for harvesting! (Real-time weather integration coming soon).",
        "pest": "For pests, we recommend organic neem oil spray initially. For severe infestations, consult an agronome.",
        "hello": "Namaste! 🙏 I am KropBot. How can I help you with your farming journey today?",
        "hi": "Hello there! ready to help you with crops, prices, or navigating KropKart.",
        "kropkart": "KropKart is an AI-powered marketplace connecting farmers directly to buyers, ensuring fair prices and fresh produce.",
        "loan": "KropKart partners with banks to offer Kisan Credit Cards. Check the 'Finance' section in your dashboard."
    }
    
    # Fuzzy matching logic
    best_response = None
    for key in responses:
        if key in msg:
            best_response = responses[key]
            break
            
    if not best_response:
        # Fallback for common agriculture terms not explicitly caught
        if any(x in msg for x in ["corn", "maize", "dal", "pulses", "gram"]):
            best_response = "We have listings for that crop! Please check the <a href='/citizen'>Marketplace</a> for live availability."
        elif any(x in msg for x in ["login", "signin", "account"]):
            best_response = "You can <a href='/login'>Login here</a>. If you don't have an account, please <a href='/register'>Register</a>."
        else:
            best_response = "I'm not sure about that specific query. Try asking about:<br>• Crop Prices (Rice, Wheat)<br>• Buying/Selling<br>• Organic Farming<br>• Government Schemes"
            
    return jsonify({"response": best_response})

@app.route("/admin")
def admin():
    if "user" not in session: return redirect("/login")
    if session.get("user_type") != "admin":
        flash("Unauthorized access!", "error")
        return redirect("/dashboard")
    
    db_local = ensure_db_connection()
    
    # Fetch Data
    users_list = list(db_local.users.find())
    products_list = list(db_local.products.find())
    orders_list = list(db_local.orders.find().sort("date", -1))
    
    # Calculate Stats
    total_users = len(users_list)
    total_products = len(products_list)
    total_orders = len(orders_list)
    total_revenue = sum(float(order.get('amount', 0)) for order in orders_list)
    
    user_counts = {}
    for u in users_list:
        rtype = u.get("user_type", "unknown")
        user_counts[rtype] = user_counts.get(rtype, 0) + 1
        
    return render_template("admin.html", 
                           total_revenue=total_revenue, 
                           total_users=total_users, 
                           total_products=total_products,
                           total_orders=total_orders,
                           recent_orders=orders_list[:50],
                           user_counts=user_counts)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=int(os.getenv("PORT", 5000)))
