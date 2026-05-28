# Storelio

Storelio is a scalable multi-vendor marketplace backend built for modern e-commerce platforms. It enables marketplace owners to manage vendors, products, orders, and payments while allowing sellers to connect their Shopify, WooCommerce, and Wix stores seamlessly.

The backend is designed with modular architecture, making it flexible, scalable, and easy to extend.

---

# 🚀 Core Features

* Multi-vendor marketplace system
* Seller onboarding & management
* Shopify integration
* WooCommerce integration
* Wix integration
* Product synchronization
* Inventory management
* Order processing system
* Discount & coupon management
* Payment integrations
* Shipping management
* Notifications system
* Wishlist support
* GraphQL APIs
* REST APIs
* SEO & page management
* Webhooks support
* Analytics & external services support

---

# 🛠️ Tech Stack

* Python
* Django
* Django REST Framework
* GraphQL
* PostgreSQL / MySQL
* JWT Authentication
* OAuth Integrations

---

# 📂 Project Structure

## Core Modules

### `account`

Handles user authentication, registration, login, permissions, and account management.

### `app`

Main application configuration and startup logic.

### `brand`

Manages product brands and related metadata.

### `checkout`

Handles checkout flow, cart processing, and order placement.

### `core`

Contains shared utilities, base models, common configurations, and helper functions used across the project.

### `csv`

CSV import/export functionality for products and marketplace data.

### `data_feeds`

Handles marketplace feeds and external data synchronization.

### `discount`

Coupon codes, promotional campaigns, and discount logic.

### `external_services`

Third-party integrations and external API services.

### `giftcard`

Gift card creation, validation, and redemption system.

### `graphql`

GraphQL APIs and schema definitions.

### `invoice`

Invoice generation and billing functionality.

### `menu`

Dynamic menu and navigation management.

### `notifications`

Email, SMS, and in-app notification system.

### `order`

Order management, tracking, and processing.

### `page`

CMS-style page management system.

### `payment`

Payment gateways and transaction handling.

### `plugins`

Custom plugins and marketplace extensions.

### `product`

Product catalog, inventory, variants, and product management.

### `python_scripts`

Utility and automation scripts.

### `rest_apis`

REST API endpoints and serializers.

### `seo`

SEO optimization and metadata management.

### `shipping`

Shipping methods, delivery calculations, and logistics support.

### `site`

Marketplace site-level configuration and settings.

### `static`

Static assets and public resources.

### `store`

Vendor store management and storefront handling.

### `support`

Customer support and help system.

### `tests`

Automated test cases and testing utilities.

### `utilities`

Reusable helper utilities and common functions.

### `warehouse`

Warehouse and stock management system.

### `webhook`

Webhook handling for third-party integrations.

### `wishlist`

Wishlist and saved products functionality.

### `wsgi / asgi`

Deployment and server gateway configurations.

---

# 📦 Installation

Clone the repository:

```bash id="g8cc6t"
git clone https://github.com/PriyanshuBoss/Storelio.git
```

Move into project directory:

```bash id="d85r4o"
cd Storelio
```

Create virtual environment:

```bash id="t4b62t"
python -m venv venv
```

Activate virtual environment:

### Windows

```bash id="cbw4pf"
venv\Scripts\activate
```

### macOS/Linux

```bash id="0s72m9"
source venv/bin/activate
```

Install dependencies:

```bash id="zl7ayv"
pip install -r requirements.txt
```

Apply database migrations:

```bash id="q8r2mk"
python manage.py migrate
```

Run development server:

```bash id="mqj1za"
python manage.py runserver
```

---

# ⚙️ Configuration

All project configurations, database credentials, API keys, and third-party integration settings can be managed directly inside the `settings.py` file.

Update the required values before running the project.

---

# 🔗 Supported Integrations

* Shopify
* WooCommerce
* Wix

---

# 📡 APIs

Storelio provides both REST and GraphQL APIs for frontend and third-party integrations.

---

# 🌍 Vision

Storelio aims to simplify marketplace infrastructure by enabling creators, startups, and businesses to launch scalable multi-vendor commerce platforms with powerful seller integrations.

---

# 🤝 Contributing

Contributions, feature suggestions, and improvements are welcome.

## Steps

1. Fork the repository
2. Create a new branch
3. Commit your changes
4. Push to your branch
5. Open a Pull Request

---

# 📄 License

This project is licensed under the MIT License.

---

# 👨‍💻 Author

Built with ❤️ by PriyanshuBoss
