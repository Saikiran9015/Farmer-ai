# KropKart Setup Guide

## 1. Environment Setup

### Create .env file with:
```env
SECRET_KEY=your-secret-key-here
MONGO_URI=mongodb+srv://abbusaikiranvarma_db_user:IVCtC9UxaemhYQ73@cluster0.qg7gv3a.mongodb.net/?appName=Cluster0
PORT=5000
```

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

## 3. Initialize Database

The database is auto-initialized when the Flask app starts. Collections created:

```
KropKart (Database)
├── users           # User accounts and profiles
├── products        # Products and inventory
├── orders          # Customer orders
├── categories      # Product categories
├── shipments       # Order shipments and tracking
└── admin           # Admin accounts
```

## 4. User Schema (in 'users' collection)

```json
{
  "_id": ObjectId,
  "name": "User Full Name",
  "email": "user@example.com",
  "password": "hashed_password",
  "user_type": "farmer|business|citizen",
  "created_at": "2025-01-01T00:00:00",
  "updated_at": "2025-01-01T00:00:00",
  "is_active": true,
  "profile": {
    "phone": "+91XXXXXXXXXX",
    "address": "Street Address",
    "city": "City Name",
    "state": "State Name",
    "pincode": "123456"
  },
  "wallet": 0,
  "total_orders": 0,
  "total_spent": 0
}
```

## 5. Run Flask App

```bash
python app.py
```

Visit: `http://localhost:5000`

## 6. User Types

- **🌾 Farmer**: Agricultural producers selling their products
- **💼 Business**: Retailers and sellers offering agricultural supplies
- **👤 Citizen**: General buyers purchasing products

## 7. Database Indexes

Automatically created for performance:
- `users.email` (unique)
- `products.category`
- `orders.user_email`

---

**Note**: All user data is stored in the `users` collection with structured fields for easy retrieval and updates.
