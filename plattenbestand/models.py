from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='fertigung')
    # fertigung: eigenen Standort sehen + Werte eintragen
    # beschichter: wie bereichsleiter (Daten sehen + ändern)
    # bereichsleiter: wie fertigung + Daten ändern
    # admin: alles + Benutzerverwaltung
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True)
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)

    location = db.relationship('Location', backref='users')
    logs = db.relationship('AuditLog', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(
            password.encode('utf-8'), self.password_hash.encode('utf-8')
        )

    @property
    def is_active(self):
        return self.is_active_user

    def can_view_location(self, loc_id):
        if self.role == 'admin':
            return True
        return self.location_id == loc_id

    def can_edit(self):
        return self.role in ('beschichter', 'bereichsleiter', 'admin')

    def can_enter(self):
        return True  # Alle Rollen dürfen Werte eintragen


class Location(db.Model):
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)

    def __repr__(self):
        return f'<Location {self.name}>'


class MaterialType(db.Model):
    """Materialart, z.B. Beschichtetes Styropor LPS, Unbeschichtete PU Platten..."""
    __tablename__ = 'material_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    products = db.relationship('Product', backref='material_type', lazy='dynamic',
                               order_by='Product.length_mm, Product.strength_mm')

    def __repr__(self):
        return f'<MaterialType {self.name}>'


class Product(db.Model):
    """Ein konkretes Produkt = Materialart + Länge + Stärke."""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    material_type_id = db.Column(db.Integer, db.ForeignKey('material_types.id'), nullable=False)
    length_mm = db.Column(db.Integer, nullable=False)    # z.B. 1650, 1900, 2250...
    strength_mm = db.Column(db.Integer, nullable=False)   # z.B. 15, 25, 35, 40...

    inventories = db.relationship('Inventory', backref='product', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('material_type_id', 'length_mm', 'strength_mm',
                            name='uq_product'),
    )

    @property
    def label(self):
        return f'{self.length_mm} x {self.strength_mm} mm'

    def __repr__(self):
        return f'<Product {self.material_type.name} {self.length_mm}x{self.strength_mm}>'


class Inventory(db.Model):
    """Ein Bestandseintrag: Produkt + Standort + Datum + Werte."""
    __tablename__ = 'inventory'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)

    beginn = db.Column(db.Integer, default=0)
    abgang = db.Column(db.Integer, default=0)
    zugang = db.Column(db.Integer, default=0)
    abfall = db.Column(db.Integer, default=0)
    summe = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    location = db.relationship('Location', backref='inventories')

    __table_args__ = (
        db.UniqueConstraint('product_id', 'location_id', 'date',
                            name='uq_inventory_entry'),
    )


class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
