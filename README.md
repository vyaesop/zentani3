# Zentanee — Clothing & Apparel E-commerce Store

[Live Demo](https://www.zentanee.com.et/)  

## 💡 Project Description

Zentanee is a full-stack e-commerce web application for selling clothes and apparel.  
Users can browse products, add items to cart, and purchase clothing. The website is built using Django (backend), HTML/CSS/JavaScript (frontend), and PostgreSQL as the database, offering a clean, maintainable, and scalable architecture.

![Project Image](https://res.cloudinary.com/dzak0zcmt/image/upload/v1/media/product/Screenshot_2025-11-28_120943_ovahi7)
![Project Image](https://res.cloudinary.com/dzak0zcmt/image/upload/v1/media/product-images/Screenshot_2025-11-28_121113_pvpgmw)

## 🧰 Tech Stack

- **Backend**: Django (Python) — models, views, routing, authentication, business logic  
- **Frontend**: HTML, CSS, JavaScript — responsive UI, dynamic interactions  
- **Database**: PostgreSQL — storing product, user, order, cart and related data  
- (Optionally) Any other libraries / tools you use (e.g. for image handling, payments, static files)  

## ✅ Key Features

- Product listing: clothes/apparel with images, descriptions, prices  
- Product detail pages  
- Shopping cart: add/remove items, adjust quantities  
- User authentication: sign-up, login (optional, if implemented)  
- Order placement (or checkout flow — if implemented)  
- Admin panel (via Django admin) to manage products, orders, users  
- Clean design and responsive layout for better UX  

## 🚀 Getting Started (Local Development)

These steps will help you run the project locally:

```bash
# 1. Clone the repository
git clone https://github.com/vyaesop/zentani3.git
cd zentani3

# 2. (Recommended) Create a Python virtual environment
python3 -m venv venv
source venv/bin/activate     # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables / settings
#    e.g. secret key, DEBUG flag, allowed hosts, database credentials, etc.

# 5. Configure PostgreSQL
#    Make sure PostgreSQL is installed; create a database and adjust settings accordingly

# 6. Run migrations
python manage.py migrate

# 7. (Optional) Create a superuser for admin access
python manage.py createsuperuser

# 8. Run the development server
python manage.py runserver

# 9. Open in browser
#    Visit http://127.0.0.1:8000 to see the site
