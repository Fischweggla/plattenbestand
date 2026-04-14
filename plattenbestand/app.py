import json
import os
from datetime import datetime, timezone, date as dt_date

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length

from config import Config
from models import db, User, Location, MaterialType, Product, Inventory, AuditLog, PlanEntry
from holidays_bayern import get_holidays, is_holiday, get_holiday_name

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(os.path.join(app.instance_path), exist_ok=True)

csrf = CSRFProtect(app)
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Bitte melden Sie sich an.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def log_action(action, entity_type=None, entity_id=None, details=None):
    entry = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        ip_address=request.remote_addr,
    )
    db.session.add(entry)
    db.session.commit()


# --- Forms ---
class LoginForm(FlaskForm):
    username = StringField('Benutzername', validators=[DataRequired()])
    password = PasswordField('Passwort', validators=[DataRequired()])


class UserForm(FlaskForm):
    username = StringField('Benutzername', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('E-Mail', validators=[DataRequired(), Email()])
    full_name = StringField('Vollständiger Name', validators=[DataRequired()])
    role = SelectField('Rolle', choices=[
        ('fertigung', 'Fertigung'),
        ('beschichter', 'Beschichter'),
        ('bereichsleiter', 'Bereichsleiter'),
        ('admin', 'Administrator'),
    ])
    location_id = SelectField('Standort', coerce=int)
    password = PasswordField('Passwort')
    is_active_user = BooleanField('Aktiv', default=True)


# --- Auth ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active:
            login_user(user)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            log_action('login')
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Ungültiger Benutzername oder Passwort.', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    log_action('logout')
    logout_user()
    return redirect(url_for('login'))


# --- Dashboard ---
@app.route('/')
@login_required
def dashboard():
    if current_user.role == 'admin':
        locations = Location.query.all()
    else:
        locations = [current_user.location] if current_user.location else []

    location_stats = []
    for loc in locations:
        latest = (
            db.session.query(db.func.max(Inventory.date))
            .filter(Inventory.location_id == loc.id)
            .scalar()
        )
        total = 0
        if latest:
            total = (
                db.session.query(db.func.sum(Inventory.summe))
                .filter(Inventory.location_id == loc.id, Inventory.date == latest)
                .scalar()
            ) or 0
        location_stats.append({
            'location': loc,
            'latest_date': latest,
            'total_stock': total,
        })

    material_types = MaterialType.query.order_by(MaterialType.sort_order).all()

    return render_template('dashboard.html',
                           location_stats=location_stats,
                           material_types=material_types)


# --- Dateneingabe ---
@app.route('/entry')
@login_required
def entry_select():
    """Workflow: Standort -> Datum -> Materialart -> Länge -> Stärke."""
    from datetime import timedelta

    if current_user.role == 'admin':
        locations = Location.query.all()
    else:
        locations = [current_user.location] if current_user.location else []

    material_types = MaterialType.query.order_by(MaterialType.sort_order).all()

    location_id = request.args.get('location', type=int)
    date_str = request.args.get('date')
    material_id = request.args.get('material', type=int)
    length_val = request.args.get('length', type=int)
    strength_val = request.args.get('strength', type=int)

    sel_location = None
    sel_date = None
    sel_material = None
    sel_length = None
    sel_strength = None

    # Hilfsfunktion: aktuelle Auswahl als dict für URL-Bau
    def sel_args(**overrides):
        args = {}
        if sel_location:
            args['location'] = sel_location.id
        if sel_date:
            args['date'] = sel_date.isoformat()
        if sel_material:
            args['material'] = sel_material.id
        if sel_length:
            args['length'] = sel_length
        if sel_strength:
            args['strength'] = sel_strength
        args.update(overrides)
        return args

    # --- Schritt 1: Standort ---
    if locations and len(locations) == 1:
        sel_location = locations[0]
        location_id = sel_location.id
    elif location_id:
        sel_location = db.session.get(Location, location_id)
        if sel_location and current_user.role != 'admin' and current_user.location_id != location_id:
            sel_location = None

    if not sel_location:
        return render_template('entry_select.html', step=1,
                               locations=locations, material_types=material_types,
                               sel_location=None, sel_date=None,
                               sel_material=None, sel_length=None, sel_strength=None,
                               sel_args=sel_args)

    # --- Schritt 2: Datum ---
    if date_str:
        try:
            sel_date = dt_date.fromisoformat(date_str)
        except ValueError:
            sel_date = None

    if not sel_date:
        today = dt_date.today()
        date_options = []
        day_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
        for offset in range(0, 7):
            d = today - timedelta(days=offset)
            label = 'Heute' if offset == 0 else 'Gestern' if offset == 1 else day_names[d.weekday()]
            date_options.append(type('D', (), {'date': d, 'label': label, 'is_today': offset == 0})())

        return render_template('entry_select.html', step=2,
                               locations=locations, material_types=material_types,
                               sel_location=sel_location, sel_date=None,
                               sel_material=None, sel_length=None, sel_strength=None,
                               date_options=date_options, sel_args=sel_args)

    # --- Schritt 3: Materialart ---
    if material_id:
        sel_material = db.session.get(MaterialType, material_id)

    if not sel_material:
        return render_template('entry_select.html', step=3,
                               locations=locations, material_types=material_types,
                               sel_location=sel_location, sel_date=sel_date,
                               sel_material=None, sel_length=None, sel_strength=None,
                               sel_args=sel_args)

    # Verfügbare Längen und Stärken für diese Materialart
    mat_products = Product.query.filter_by(material_type_id=sel_material.id).all()
    mat_lengths = sorted(set(p.length_mm for p in mat_products))
    mat_strengths = sorted(set(p.strength_mm for p in mat_products))

    # --- Schritt 4: Länge ---
    if length_val and length_val in mat_lengths:
        sel_length = length_val

    if not sel_length:
        return render_template('entry_select.html', step=4,
                               locations=locations, material_types=material_types,
                               sel_location=sel_location, sel_date=sel_date,
                               sel_material=sel_material, sel_length=None, sel_strength=None,
                               mat_lengths=mat_lengths, sel_args=sel_args)

    # --- Schritt 5: Stärke ---
    # Stärken für gewählte Materialart + Länge
    length_strengths = sorted(set(
        p.strength_mm for p in mat_products if p.length_mm == sel_length
    ))

    if strength_val and strength_val in length_strengths:
        sel_strength = strength_val

    if not sel_strength:
        # Bei nur einer Stärke direkt weiter
        if len(length_strengths) == 1:
            sel_strength = length_strengths[0]
        else:
            return render_template('entry_select.html', step=5,
                                   locations=locations, material_types=material_types,
                                   sel_location=sel_location, sel_date=sel_date,
                                   sel_material=sel_material, sel_length=sel_length,
                                   sel_strength=None,
                                   length_strengths=length_strengths, sel_args=sel_args)

    # Alle Schritte abgeschlossen -> zum Eingabeformular
    return redirect(url_for('entry_form',
                            location_id=sel_location.id,
                            material_id=sel_material.id,
                            date_str=sel_date.isoformat(),
                            length=sel_length,
                            strength=sel_strength))


@app.route('/entry/<int:location_id>/<int:material_id>/<string:date_str>', methods=['GET', 'POST'])
@login_required
def entry_form(location_id, material_id, date_str):
    """Dateneingabe-Formular: Tabelle wie in Excel."""
    location = db.session.get(Location, location_id)
    material = db.session.get(MaterialType, material_id)
    if not location or not material:
        abort(404)

    # Berechtigungsprüfung
    if current_user.role != 'admin' and current_user.location_id != location_id:
        flash('Keine Berechtigung für diesen Standort.', 'danger')
        return redirect(url_for('entry_select'))

    try:
        entry_date = dt_date.fromisoformat(date_str)
    except ValueError:
        flash('Ungültiges Datum.', 'danger')
        return redirect(url_for('entry_select'))

    # Filter nach Länge/Stärke aus Workflow
    sel_length = request.args.get('length', type=int)
    sel_strength = request.args.get('strength', type=int)

    prod_query = Product.query.filter_by(material_type_id=material_id)
    if sel_length:
        prod_query = prod_query.filter_by(length_mm=sel_length)
    if sel_strength:
        prod_query = prod_query.filter_by(strength_mm=sel_strength)
    products = prod_query.order_by(Product.length_mm, Product.strength_mm).all()

    # Vorhandene Daten laden
    existing = {}
    for inv in Inventory.query.filter(
        Inventory.product_id.in_([p.id for p in products]),
        Inventory.location_id == location_id,
        Inventory.date == entry_date,
    ).all():
        existing[inv.product_id] = inv

    # Prüfen ob vorheriger Tag existiert (für automatisches Beginn)
    from datetime import timedelta
    prev_date = entry_date - timedelta(days=1)
    # Suche letztes Datum vor entry_date
    last_date = (
        db.session.query(db.func.max(Inventory.date))
        .filter(
            Inventory.location_id == location_id,
            Inventory.date < entry_date,
            Inventory.product_id.in_([p.id for p in products]),
        )
        .scalar()
    )
    prev_data = {}
    if last_date:
        for inv in Inventory.query.filter(
            Inventory.product_id.in_([p.id for p in products]),
            Inventory.location_id == location_id,
            Inventory.date == last_date,
        ).all():
            prev_data[inv.product_id] = inv.summe

    if request.method == 'POST':
        # Berechtigungsprüfung für Änderungen
        is_new_entry = not any(existing.values())
        if not is_new_entry and not current_user.can_edit():
            flash('Nur Bereichsleiter und Admins dürfen bestehende Daten ändern.', 'danger')
            return redirect(url_for('entry_form', location_id=location_id,
                                    material_id=material_id, date_str=date_str))

        count = 0
        for product in products:
            key = f'p_{product.id}'
            abgang = request.form.get(f'{key}_abgang', 0, type=int)
            zugang = request.form.get(f'{key}_zugang', 0, type=int)
            abfall = request.form.get(f'{key}_abfall', 0, type=int)

            # Beginn = letzte Summe (automatisch)
            beginn = prev_data.get(product.id, 0)
            if product.id in existing:
                beginn = existing[product.id].beginn
            summe = beginn + zugang - abgang - abfall

            if any([abgang, zugang, abfall]) or product.id in existing:
                inv = existing.get(product.id)
                if inv:
                    old = {'abgang': inv.abgang, 'zugang': inv.zugang,
                           'abfall': inv.abfall, 'summe': inv.summe}
                    inv.beginn = beginn
                    inv.abgang = abgang
                    inv.zugang = zugang
                    inv.abfall = abfall
                    inv.summe = summe
                    new = {'abgang': abgang, 'zugang': zugang,
                           'abfall': abfall, 'summe': summe}
                    if old != new:
                        log_action('update', 'inventory', inv.id,
                                   {'product': product.label, 'old': old, 'new': new})
                else:
                    inv = Inventory(
                        product_id=product.id,
                        location_id=location_id,
                        date=entry_date,
                        beginn=beginn,
                        abgang=abgang,
                        zugang=zugang,
                        abfall=abfall,
                        summe=summe,
                    )
                    db.session.add(inv)
                    log_action('create', 'inventory', None,
                               {'product': product.label, 'values': {
                                   'beginn': beginn, 'abgang': abgang,
                                   'zugang': zugang, 'abfall': abfall, 'summe': summe}})
                count += 1

        db.session.commit()
        flash(f'{count} Einträge gespeichert.', 'success')
        return redirect(url_for('entry_form', location_id=location_id,
                                material_id=material_id, date_str=date_str))

    # Produkte nach Länge gruppieren
    products_by_length = {}
    for p in products:
        products_by_length.setdefault(p.length_mm, []).append(p)

    # Alle vorkommenden Stärken sammeln
    all_strengths = sorted(set(p.strength_mm for p in products))

    return render_template('entry_form.html',
                           location=location, material=material,
                           entry_date=entry_date,
                           products=products,
                           products_by_length=products_by_length,
                           all_strengths=all_strengths,
                           existing=existing,
                           prev_data=prev_data,
                           is_edit=bool(existing))


# --- Bestandsübersicht ---
@app.route('/inventory')
@login_required
def inventory_list():
    if current_user.role == 'admin':
        locations = Location.query.all()
    else:
        locations = [current_user.location] if current_user.location else []

    location_id = request.args.get('location', type=int)
    date_str = request.args.get('date')

    # Zugangskontrolle
    if location_id and current_user.role != 'admin':
        if current_user.location_id != location_id:
            flash('Keine Berechtigung für diesen Standort.', 'danger')
            return redirect(url_for('inventory_list'))

    material_types = MaterialType.query.order_by(MaterialType.sort_order).all()

    # Bestimme das Datum
    selected_date_obj = None
    if date_str:
        try:
            selected_date_obj = dt_date.fromisoformat(date_str)
        except ValueError:
            pass

    # Wenn kein Datum gewählt, neuestes finden
    if not selected_date_obj:
        date_sub = db.session.query(db.func.max(Inventory.date))
        if current_user.role != 'admin' and current_user.location_id:
            date_sub = date_sub.filter(Inventory.location_id == current_user.location_id)
        elif location_id:
            date_sub = date_sub.filter(Inventory.location_id == location_id)
        selected_date_obj = date_sub.scalar()

    # Daten laden - bei "Gesamt" über alle Standorte summieren
    query = (
        db.session.query(
            Product.material_type_id,
            Product.length_mm,
            Product.strength_mm,
            db.func.sum(Inventory.summe).label('total_summe'),
            db.func.sum(Inventory.zugang).label('total_zugang'),
            db.func.sum(Inventory.abgang).label('total_abgang'),
            db.func.sum(Inventory.abfall).label('total_abfall'),
            db.func.sum(Inventory.beginn).label('total_beginn'),
        )
        .join(Product, Inventory.product_id == Product.id)
        .join(Location, Inventory.location_id == Location.id)
    )

    if selected_date_obj:
        query = query.filter(Inventory.date == selected_date_obj)

    if current_user.role != 'admin':
        query = query.filter(Inventory.location_id == current_user.location_id)
    elif location_id:
        query = query.filter(Inventory.location_id == location_id)

    query = query.group_by(Product.material_type_id, Product.length_mm, Product.strength_mm)
    rows = query.all()

    # Daten nach Materialart strukturieren
    # mat_data[mat_id] = { (length, strength): {summe, zugang, abgang, abfall, beginn} }
    mat_data = {}
    for r in rows:
        mat_data.setdefault(r.material_type_id, {})
        mat_data[r.material_type_id][(r.length_mm, r.strength_mm)] = {
            'summe': r.total_summe or 0,
            'zugang': r.total_zugang or 0,
            'abgang': r.total_abgang or 0,
            'abfall': r.total_abfall or 0,
            'beginn': r.total_beginn or 0,
        }

    # Pro Materialart: verfügbare Längen und Stärken
    mat_grid = []
    for mt in material_types:
        data = mat_data.get(mt.id, {})
        products = Product.query.filter_by(material_type_id=mt.id).all()
        lengths = sorted(set(p.length_mm for p in products))
        strengths = sorted(set(p.strength_mm for p in products))
        total = sum(v['summe'] for v in data.values())
        mat_grid.append({
            'material': mt,
            'lengths': lengths,
            'strengths': strengths,
            'data': data,
            'total': total,
        })

    # Verfügbare Daten für Datumsfilter
    date_query = db.session.query(Inventory.date).distinct().order_by(Inventory.date.desc())
    if current_user.role != 'admin':
        date_query = date_query.filter(Inventory.location_id == current_user.location_id)
    available_dates = [d[0] for d in date_query.limit(60).all()]

    # Aktiver Standortname
    selected_location_obj = None
    if location_id:
        selected_location_obj = db.session.get(Location, location_id)

    return render_template('inventory.html',
                           locations=locations,
                           material_types=material_types,
                           mat_grid=mat_grid,
                           selected_location=location_id,
                           selected_location_obj=selected_location_obj,
                           selected_date=date_str,
                           selected_date_obj=selected_date_obj,
                           available_dates=available_dates)


# --- Beschichtungsplan ---
@app.route('/plan')
@login_required
def plan_view():
    """Wochenansicht Beschichtungsplan."""
    from datetime import timedelta

    if current_user.role == 'admin':
        locations = Location.query.all()
    else:
        locations = [current_user.location] if current_user.location else []

    location_id = request.args.get('location', type=int)
    week_offset = request.args.get('week', 0, type=int)

    # Standard-Standort
    if not location_id:
        location_id = locations[0].id if locations else None
    sel_location = db.session.get(Location, location_id) if location_id else None

    if sel_location and current_user.role != 'admin' and current_user.location_id != location_id:
        flash('Keine Berechtigung für diesen Standort.', 'danger')
        return redirect(url_for('plan_view'))

    # Woche berechnen (Mo-Fr)
    today = dt_date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = []
    holidays_this_year = get_holidays(monday.year)
    # Falls die Woche über den Jahreswechsel geht
    if monday.year != (monday + timedelta(days=4)).year:
        holidays_this_year.update(get_holidays(monday.year + 1))

    for i in range(5):  # Mo-Fr
        d = monday + timedelta(days=i)
        holiday_name = holidays_this_year.get(d)
        week_days.append({
            'date': d,
            'weekday': ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag'][i],
            'is_holiday': holiday_name is not None,
            'holiday_name': holiday_name,
            'is_today': d == today,
        })

    # Plan-Einträge laden
    entries = {}
    if sel_location:
        for pe in (
            PlanEntry.query
            .filter(
                PlanEntry.location_id == location_id,
                PlanEntry.date >= monday,
                PlanEntry.date <= monday + timedelta(days=4),
            )
            .order_by(PlanEntry.date, PlanEntry.id)
            .all()
        ):
            entries.setdefault(pe.date, []).append(pe)

    # Kalenderwochen-Infos
    kw = monday.isocalendar()[1]

    can_edit_plan = current_user.role in ('bereichsleiter', 'admin')

    material_types = MaterialType.query.order_by(MaterialType.sort_order).all()

    return render_template('plan.html',
                           locations=locations,
                           sel_location=sel_location,
                           selected_location=location_id,
                           week_days=week_days,
                           entries=entries,
                           kw=kw,
                           week_offset=week_offset,
                           monday=monday,
                           can_edit_plan=can_edit_plan,
                           material_types=material_types)


@app.route('/plan/add', methods=['POST'])
@login_required
def plan_add():
    """Eintrag zum Beschichtungsplan hinzufügen."""
    if current_user.role not in ('bereichsleiter', 'admin'):
        flash('Nur Bereichsleiter und Admins dürfen den Plan bearbeiten.', 'danger')
        return redirect(url_for('plan_view'))

    plan_date = request.form.get('date')
    location_id = request.form.get('location_id', type=int)
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', 0, type=int)
    notes = request.form.get('notes', '').strip()
    week_offset = request.form.get('week_offset', 0, type=int)

    if not plan_date or not product_id or not location_id:
        flash('Bitte alle Felder ausfüllen.', 'warning')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    try:
        d = dt_date.fromisoformat(plan_date)
    except ValueError:
        flash('Ungültiges Datum.', 'danger')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    if is_holiday(d):
        flash(f'{d.strftime("%d.%m.%Y")} ist ein Feiertag.', 'warning')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    entry = PlanEntry(
        date=d,
        location_id=location_id,
        product_id=product_id,
        quantity=quantity,
        notes=notes,
        created_by=current_user.id,
    )
    db.session.add(entry)
    db.session.commit()
    log_action('create', 'plan', entry.id, {
        'date': d.isoformat(), 'product_id': product_id, 'quantity': quantity})

    flash('Eintrag hinzugefügt.', 'success')
    return redirect(url_for('plan_view', week=week_offset, location=location_id))


@app.route('/plan/delete/<int:entry_id>', methods=['POST'])
@login_required
def plan_delete(entry_id):
    if current_user.role not in ('bereichsleiter', 'admin'):
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('plan_view'))

    entry = db.session.get(PlanEntry, entry_id)
    if not entry:
        flash('Eintrag nicht gefunden.', 'danger')
        return redirect(url_for('plan_view'))

    week_offset = request.form.get('week_offset', 0, type=int)
    location_id = entry.location_id
    log_action('delete', 'plan', entry.id, {'date': entry.date.isoformat()})
    db.session.delete(entry)
    db.session.commit()
    flash('Eintrag gelöscht.', 'success')
    return redirect(url_for('plan_view', week=week_offset, location=location_id))


@app.route('/plan/products')
@login_required
def plan_products():
    """JSON: Produkte für Dropdown, optional gefiltert nach Material."""
    material_id = request.args.get('material', type=int)
    query = (
        db.session.query(Product, MaterialType)
        .join(MaterialType, Product.material_type_id == MaterialType.id)
        .order_by(MaterialType.sort_order, Product.length_mm, Product.strength_mm)
    )
    if material_id:
        query = query.filter(Product.material_type_id == material_id)
    results = query.all()
    return jsonify([{
        'id': p.id,
        'label': f'{mt.name} — {p.length_mm} x {p.strength_mm} mm',
        'material': mt.name,
        'length': p.length_mm,
        'strength': p.strength_mm,
    } for p, mt in results])


@app.route('/plan/add-low-stock', methods=['POST'])
@login_required
def plan_add_low_stock():
    """Niedrigste Bestände direkt in den Plan übernehmen."""
    if current_user.role not in ('bereichsleiter', 'admin'):
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('plan_view'))

    plan_date = request.form.get('date')
    location_id = request.form.get('location_id', type=int)
    week_offset = request.form.get('week_offset', 0, type=int)
    count = request.form.get('count', 5, type=int)

    try:
        d = dt_date.fromisoformat(plan_date)
    except (ValueError, TypeError):
        flash('Ungültiges Datum.', 'danger')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    if is_holiday(d):
        flash('Kann keine Einträge an Feiertagen anlegen.', 'warning')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    # Niedrigste Bestände finden
    latest = db.session.query(db.func.max(Inventory.date)).scalar()
    if not latest:
        flash('Keine Bestandsdaten vorhanden.', 'warning')
        return redirect(url_for('plan_view', week=week_offset, location=location_id))

    low_q = (
        db.session.query(
            Product.id,
            db.func.sum(Inventory.summe).label('total'),
        )
        .join(Product, Inventory.product_id == Product.id)
        .filter(Inventory.date == latest)
    )
    if location_id:
        low_q = low_q.filter(Inventory.location_id == location_id)
    low_items = (
        low_q
        .group_by(Product.id)
        .having(db.func.sum(Inventory.summe) >= 0)
        .order_by('total')
        .limit(count)
        .all()
    )

    added = 0
    for item in low_items:
        entry = PlanEntry(
            date=d, location_id=location_id,
            product_id=item.id, quantity=0,
            notes=f'Niedriger Bestand ({item.total} Stk.)',
            created_by=current_user.id,
        )
        db.session.add(entry)
        added += 1

    db.session.commit()
    log_action('create', 'plan', None, {'action': 'low_stock', 'count': added, 'date': d.isoformat()})
    flash(f'{added} Produkte mit niedrigstem Bestand eingeplant.', 'success')
    return redirect(url_for('plan_view', week=week_offset, location=location_id))


# --- Auswertungen ---
@app.route('/reports')
@login_required
def reports():
    if current_user.role == 'admin':
        locations = Location.query.all()
    else:
        locations = [current_user.location] if current_user.location else []
    material_types = MaterialType.query.order_by(MaterialType.sort_order).all()
    return render_template('reports.html', locations=locations,
                           material_types=material_types)


@app.route('/reports/data')
@login_required
def reports_data():
    report_type = request.args.get('type')
    location_id = request.args.get('location', type=int)

    if current_user.role != 'admin':
        location_id = current_user.location_id

    def loc_filter(q):
        if location_id:
            return q.filter(Inventory.location_id == location_id)
        if current_user.role != 'admin':
            return q.filter(Inventory.location_id == current_user.location_id)
        return q

    # --- KPIs: Gesamtbestand, Bewegungen, Abfallquote ---
    if report_type == 'kpis':
        latest = loc_filter(db.session.query(db.func.max(Inventory.date))).scalar()
        if not latest:
            return jsonify({'total': 0, 'zugang': 0, 'abgang': 0, 'abfall': 0, 'date': None})
        q = loc_filter(
            db.session.query(
                db.func.sum(Inventory.summe),
                db.func.sum(Inventory.zugang),
                db.func.sum(Inventory.abgang),
                db.func.sum(Inventory.abfall),
            ).filter(Inventory.date == latest)
        ).one()
        return jsonify({
            'total': q[0] or 0, 'zugang': q[1] or 0,
            'abgang': q[2] or 0, 'abfall': q[3] or 0,
            'date': latest.isoformat() if latest else None,
        })

    # --- Verteilung nach Materialart (Donut) ---
    if report_type == 'by_material':
        latest = loc_filter(db.session.query(db.func.max(Inventory.date))).scalar()
        if not latest:
            return jsonify([])
        rows = loc_filter(
            db.session.query(
                MaterialType.name, db.func.sum(Inventory.summe).label('total')
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(MaterialType, Product.material_type_id == MaterialType.id)
            .filter(Inventory.date == latest)
            .group_by(MaterialType.name)
            .order_by(MaterialType.sort_order)
        ).all()
        return jsonify([{'name': r.name, 'value': r.total or 0} for r in rows if r.total])

    # --- Verteilung nach Standort (Donut) ---
    if report_type == 'by_location':
        latest = db.session.query(db.func.max(Inventory.date)).scalar()
        if not latest:
            return jsonify([])
        rows = (
            db.session.query(
                Location.name, db.func.sum(Inventory.summe).label('total')
            )
            .join(Location, Inventory.location_id == Location.id)
            .filter(Inventory.date == latest)
            .group_by(Location.name)
        ).all()
        return jsonify([{'name': r.name, 'value': r.total or 0} for r in rows if r.total])

    # --- Bewegungen (Wasserfall: Zugang vs Abgang vs Abfall) pro Material ---
    if report_type == 'movements':
        latest = loc_filter(db.session.query(db.func.max(Inventory.date))).scalar()
        if not latest:
            return jsonify([])
        rows = loc_filter(
            db.session.query(
                MaterialType.name,
                db.func.sum(Inventory.zugang).label('zugang'),
                db.func.sum(Inventory.abgang).label('abgang'),
                db.func.sum(Inventory.abfall).label('abfall'),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(MaterialType, Product.material_type_id == MaterialType.id)
            .filter(Inventory.date == latest)
            .group_by(MaterialType.name)
            .order_by(MaterialType.sort_order)
        ).all()
        return jsonify([{
            'name': r.name[:25], 'zugang': r.zugang or 0,
            'abgang': r.abgang or 0, 'abfall': r.abfall or 0,
        } for r in rows if (r.zugang or r.abgang or r.abfall)])

    # --- Zeitverlauf (Bestand) ---
    if report_type == 'timeline':
        query = (
            db.session.query(
                Inventory.date,
                Location.name.label('loc'),
                db.func.sum(Inventory.summe).label('total')
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Location, Inventory.location_id == Location.id)
            .group_by(Inventory.date, Location.name)
            .order_by(Inventory.date)
        )
        query = loc_filter(query)
        data = {}
        for row in query.all():
            data.setdefault(row.loc, {'dates': [], 'values': []})
            data[row.loc]['dates'].append(row.date.isoformat())
            data[row.loc]['values'].append(row.total or 0)
        return jsonify(data)

    # --- Top/Bottom Produkte ---
    if report_type == 'top_bottom':
        latest = loc_filter(db.session.query(db.func.max(Inventory.date))).scalar()
        if not latest:
            return jsonify({'top': [], 'bottom': []})
        base = (
            loc_filter(
                db.session.query(
                    MaterialType.name.label('mat'),
                    Product.length_mm, Product.strength_mm,
                    db.func.sum(Inventory.summe).label('total'),
                )
                .join(Product, Inventory.product_id == Product.id)
                .join(MaterialType, Product.material_type_id == MaterialType.id)
                .filter(Inventory.date == latest)
            )
            .group_by(MaterialType.name, Product.length_mm, Product.strength_mm)
        )
        top = base.order_by(db.desc('total')).limit(10).all()
        bottom = base.having(db.func.sum(Inventory.summe) > 0).order_by('total').limit(10).all()
        fmt = lambda r: {
            'label': f"{r.mat[:20]} {r.length_mm}x{r.strength_mm}",
            'value': r.total or 0,
        }
        return jsonify({'top': [fmt(r) for r in top], 'bottom': [fmt(r) for r in bottom]})

    # --- Heatmap: Standorte x Materialarten ---
    if report_type == 'heatmap':
        latest = db.session.query(db.func.max(Inventory.date)).scalar()
        if not latest:
            return jsonify({'locations': [], 'materials': [], 'values': []})
        rows = (
            db.session.query(
                Location.name.label('loc'),
                MaterialType.name.label('mat'),
                db.func.sum(Inventory.summe).label('total'),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(MaterialType, Product.material_type_id == MaterialType.id)
            .join(Location, Inventory.location_id == Location.id)
            .filter(Inventory.date == latest)
            .group_by(Location.name, MaterialType.name)
        ).all()
        locs = sorted(set(r.loc for r in rows))
        mats = sorted(set(r.mat for r in rows))
        lookup = {(r.loc, r.mat): r.total or 0 for r in rows}
        values = []
        for mi, m in enumerate(mats):
            for li, l in enumerate(locs):
                values.append({'x': li, 'y': mi, 'v': lookup.get((l, m), 0)})
        return jsonify({'locations': locs, 'materials': [m[:22] for m in mats], 'values': values})

    return jsonify({})


# --- Benutzerverwaltung ---
@app.route('/users')
@login_required
def user_list():
    if current_user.role != 'admin':
        flash('Nur Administratoren.', 'danger')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.username).all()
    return render_template('users.html', users=users)


@app.route('/users/new', methods=['GET', 'POST'])
@login_required
def user_create():
    if current_user.role != 'admin':
        flash('Nur Administratoren.', 'danger')
        return redirect(url_for('dashboard'))

    form = UserForm()
    form.location_id.choices = [(0, '-- Alle Standorte --')] + [
        (l.id, l.name) for l in Location.query.all()
    ]
    if form.validate_on_submit():
        if not form.password.data:
            flash('Passwort ist erforderlich.', 'danger')
            return render_template('user_form.html', form=form, title='Neuer Benutzer')
        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            role=form.role.data,
            location_id=form.location_id.data if form.location_id.data != 0 else None,
            is_active_user=form.is_active_user.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        log_action('create', 'user', user.id, {'username': user.username})
        flash(f'Benutzer {user.username} angelegt.', 'success')
        return redirect(url_for('user_list'))

    return render_template('user_form.html', form=form, title='Neuer Benutzer')


@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    if current_user.role != 'admin':
        flash('Nur Administratoren.', 'danger')
        return redirect(url_for('dashboard'))

    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('user_list'))

    form = UserForm(obj=user)
    form.location_id.choices = [(0, '-- Alle Standorte --')] + [
        (l.id, l.name) for l in Location.query.all()
    ]
    if not form.is_submitted():
        form.location_id.data = user.location_id or 0

    if form.validate_on_submit():
        user.username = form.username.data
        user.email = form.email.data
        user.full_name = form.full_name.data
        user.role = form.role.data
        user.location_id = form.location_id.data if form.location_id.data != 0 else None
        user.is_active_user = form.is_active_user.data
        if form.password.data:
            user.set_password(form.password.data)
        db.session.commit()
        log_action('update', 'user', user.id, {'username': user.username})
        flash('Benutzer aktualisiert.', 'success')
        return redirect(url_for('user_list'))

    return render_template('user_form.html', form=form, title='Benutzer bearbeiten')


# --- Audit-Log ---
@app.route('/audit')
@login_required
def audit_log():
    if current_user.role != 'admin':
        flash('Nur Administratoren.', 'danger')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=50)
    return render_template('audit.html', logs=logs)


# --- API (vorbereitet für ERP) ---
@app.route('/api/v1/inventory')
@csrf.exempt
def api_inventory():
    location = request.args.get('location')
    date_str = request.args.get('date')
    query = (
        db.session.query(Inventory, Product, MaterialType, Location)
        .join(Product, Inventory.product_id == Product.id)
        .join(MaterialType, Product.material_type_id == MaterialType.id)
        .join(Location, Inventory.location_id == Location.id)
    )
    if location:
        query = query.filter(Location.code == location)
    if date_str:
        try:
            query = query.filter(Inventory.date == dt_date.fromisoformat(date_str))
        except ValueError:
            return jsonify({'error': 'Format: YYYY-MM-DD'}), 400

    results = query.order_by(Inventory.date.desc()).limit(1000).all()
    data = [{
        'id': inv.id, 'date': inv.date.isoformat(),
        'location': {'code': loc.code, 'name': loc.name},
        'material': mat.name,
        'length_mm': prod.length_mm, 'strength_mm': prod.strength_mm,
        'beginn': inv.beginn, 'zugang': inv.zugang,
        'abgang': inv.abgang, 'abfall': inv.abfall, 'summe': inv.summe,
    } for inv, prod, mat, loc in results]
    return jsonify({'count': len(data), 'data': data})


@app.route('/api/v1/locations')
@csrf.exempt
def api_locations():
    return jsonify([{'id': l.id, 'code': l.code, 'name': l.name}
                    for l in Location.query.all()])


# --- Init ---
def init_db():
    db.create_all()

    if not Location.query.first():
        db.session.add_all([
            Location(name='Birkach', code='99'),
            Location(name='Brandis', code='98'),
            Location(name='Dinkelsbühl', code='96'),
        ])
        db.session.flush()

    if not MaterialType.query.first():
        materials = [
            ('Beschichtetes Styropor LPS', 1),
            ('Unbeschichtetes Styropor LPS', 2),
            ('Beschichtete PU Platten', 3),
            ('Unbeschichtete PU Platten', 4),
            ('Beschichtete Mineralfaser LPS', 5),
            ('Unbeschichtete Mineralfaserplatten LPS', 6),
            ('Unbeschichtete Holzfaserplatte', 7),
            ('Beschichtete Holzfaserplatte', 8),
            ('Unbeschichtet gelbes Styropor / Perimeter B-3000', 9),
            ('Beschichtet gelbes Styropor / Perimeter B-3000', 10),
        ]
        mat_objects = {}
        for name, order in materials:
            mt = MaterialType(name=name, sort_order=order)
            db.session.add(mt)
            mat_objects[name] = mt
        db.session.flush()

        # Produkte anlegen basierend auf der Excel-Analyse
        lengths = [1650, 1900, 2250, 2350, 2550, 2750]
        lengths_dkb_extra = [3020]

        product_defs = {
            'Beschichtetes Styropor LPS': {
                'strengths': [15, 25, 35, 40],
                'lengths': lengths + lengths_dkb_extra,
            },
            'Unbeschichtetes Styropor LPS': {
                'strengths': [11, 21, 31, 36, 45],
                'lengths': lengths + lengths_dkb_extra,
            },
            'Beschichtete PU Platten': {
                'strengths': [25],
                'lengths': lengths,
            },
            'Unbeschichtete PU Platten': {
                'strengths': [21],
                'lengths': lengths,
            },
            'Beschichtete Mineralfaser LPS': {
                'strengths': [25],
                'lengths': lengths,
            },
            'Unbeschichtete Mineralfaserplatten LPS': {
                'strengths': [20],
                'lengths': lengths,
            },
            'Unbeschichtete Holzfaserplatte': {
                'strengths': [20, 21],
                'lengths': [2350, 2750],
            },
            'Beschichtete Holzfaserplatte': {
                'strengths': [24, 25],
                'lengths': [2350, 2750],
            },
            'Unbeschichtet gelbes Styropor / Perimeter B-3000': {
                'strengths': [21],
                'lengths': lengths,
            },
            'Beschichtet gelbes Styropor / Perimeter B-3000': {
                'strengths': [25],
                'lengths': lengths,
            },
        }

        for mat_name, defs in product_defs.items():
            mt = mat_objects[mat_name]
            for length in defs['lengths']:
                for strength in defs['strengths']:
                    db.session.add(Product(
                        material_type_id=mt.id,
                        length_mm=length,
                        strength_mm=strength,
                    ))

    if not User.query.first():
        admin = User(
            username='admin',
            email='admin@ibe-innovativ.de',
            full_name='Administrator',
            role='admin',
            location_id=None,
        )
        admin.set_password('admin2025')
        db.session.add(admin)

    db.session.commit()


with app.app_context():
    init_db()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
