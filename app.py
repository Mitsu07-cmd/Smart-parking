# app.py
# Smart Parking System Backend - Flask, SQLite, and User/Allocation Logic
# Requires: pip install Flask flask-cors

import sqlite3
import json
from flask import Flask, jsonify, request, g
from flask_cors import CORS # Needed to allow the index.html file to fetch data

# --- Configuration ---
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
DATABASE = 'parking_system.db'

# --- Database Initialization and Helpers ---

def get_db_connection():
    """Connects to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    return conn

def init_db():
    """
    Initializes the database structure and mock data.
    This function deletes and recreates the tables on every restart.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- Drop tables to ensure a clean start ---
    cursor.execute('DROP TABLE IF EXISTS ParkingSpots')
    cursor.execute('DROP TABLE IF EXISTS Users')
    conn.commit()

    # --- Create ParkingSpots Table (Requirement 1: List of all seats) ---
    cursor.execute('''
        CREATE TABLE ParkingSpots (
            spot_id INTEGER PRIMARY KEY,
            floor TEXT NOT NULL,
            spot_type TEXT NOT NULL,  -- 'Standard' or 'Premium'
            is_occupied INTEGER NOT NULL DEFAULT 0 -- 0 for Free, 1 for Occupied
        )
    ''')

    # --- Create Users Table ---
    cursor.execute('''
        CREATE TABLE Users (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL,       -- 'Student', 'Teacher', 'Admin'
            is_premium INTEGER NOT NULL DEFAULT 0 -- 0 for Standard, 1 for Premium
        )
    ''')

    # --- Mock Data for 20 Spots (Requirement 1) ---
    spots_data = []
    
    # Parking 1 (Closer spots - IDs 1 to 10)
    # Spot 1-4: Premium (2 occupied, 2 free)
    spots_data.append((1, 'Parking 1', 'Premium', 1)) # Occupied
    spots_data.append((2, 'Parking 1', 'Premium', 0)) # Free (Best Premium Spot)
    spots_data.append((3, 'Parking 1', 'Premium', 1)) # Occupied
    spots_data.append((4, 'Parking 1', 'Premium', 0)) # Free
    # Spot 5-10: Standard (3 occupied, 3 free)
    spots_data.append((5, 'Parking 1', 'Standard', 0)) # Free (Best Standard Spot)
    spots_data.append((6, 'Parking 1', 'Standard', 1)) # Occupied
    spots_data.append((7, 'Parking 1', 'Standard', 0)) # Free
    spots_data.append((8, 'Parking 1', 'Standard', 1)) # Occupied
    spots_data.append((9, 'Parking 1', 'Standard', 0)) # Free
    spots_data.append((10, 'Parking 1', 'Standard', 1)) # Occupied

    # Parking 2 (Futher spots - IDs 11 to 20)
    # Spot 11-12: Premium (1 occupied, 1 free)
    spots_data.append((11, 'Parking 2', 'Premium', 1)) # Occupied
    spots_data.append((12, 'Parking 2', 'Premium', 0)) # Free
    # Spot 13-20: Standard (4 occupied, 4 free)
    for i in range(13, 21):
        is_occupied = 1 if i % 2 == 0 else 0
        spots_data.append((i, 'Parking 2', 'Standard', is_occupied))
    
    # Insert spot data
    cursor.executemany(
        'INSERT INTO ParkingSpots (spot_id, floor, spot_type, is_occupied) VALUES (?, ?, ?, ?)',
        spots_data
    )

    # --- Mock Data for Users (Requirement 3: Premium users) ---
    users_data = [
        (101, 'Teacher', 1),    # Premium Teacher
        (102, 'Student', 0),    # Standard Student
        (103, 'Premium Student', 1), # Premium Student
    ]
    cursor.executemany(
        'INSERT INTO Users (user_id, role, is_premium) VALUES (?, ?, ?)',
        users_data
    )

    conn.commit()
    conn.close()
    print("Database initialized with 20 spots and 3 users. Spots are reset.")


# --- API Endpoints ---

@app.route('/api/spots', methods=['GET'])
def get_spots():
    """API to list all seats and their current status."""
    conn = get_db_connection()
    spots = conn.execute('SELECT * FROM ParkingSpots').fetchall()
    conn.close()
    
    # Convert Row objects to list of dictionaries
    spots_list = [dict(spot) for spot in spots]
    return jsonify(spots_list)

@app.route('/api/user_info', methods=['POST'])
def get_user_info():
    """API to look up user role and premium status for login."""
    try:
        user_id = request.json.get('user_id')
        if user_id is None:
            return jsonify({"success": False, "error": "User ID is required"}), 400

        conn = get_db_connection()
        user = conn.execute('SELECT user_id, role, is_premium FROM Users WHERE user_id = ?', (user_id,)).fetchone()
        conn.close()

        if user:
            return jsonify({
                "success": True,
                "user_id": user['user_id'],
                "role": user['role'],
                "is_premium": user['is_premium']
            })
        else:
            return jsonify({"success": False, "error": f"User ID {user_id} not found."}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def get_least_dense_floor(cursor):
    """
    Determines the floor ('Parking 1' or 'Parking 2') with the lowest occupancy density.
    Returns the floor name string.
    """
    
    # Get total and occupied counts for each floor
    cursor.execute("""
        SELECT 
            floor,
            SUM(CASE WHEN is_occupied = 1 THEN 1 ELSE 0 END) as occupied_count,
            COUNT(spot_id) as total_count
        FROM ParkingSpots
        GROUP BY floor
    """)
    floor_data = cursor.fetchall()

    density_map = {}
    
    for row in floor_data:
        floor = row['floor']
        occupied = row['occupied_count']
        total = row['total_count']
        
        # Calculate density (handle division by zero if needed, though unlikely here)
        density = occupied / total if total > 0 else 1.0
        density_map[floor] = density

    # Find the floor with the minimum density
    # Default to 'Parking 1' if density is equal or data is missing
    least_dense_floor = 'Parking 1' 
    min_density = density_map.get('Parking 1', 1.0) # Start with P1 density

    # Compare densities
    p2_density = density_map.get('Parking 2', 1.0)
    
    if p2_density < min_density:
        least_dense_floor = 'Parking 2'
        
    return least_dense_floor

@app.route('/api/allocate', methods=['POST'])
def allocate_spot():
    """
    API for efficient parking allocation (Requirement 2 & 3).
    Uses Density-Based Allocation: find the least dense parking area first,
    then allocate the nearest spot within that area, respecting Premium status.
    """
    data = request.json
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get user status
    user = cursor.execute('SELECT is_premium FROM Users WHERE user_id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "Invalid User ID."}), 404
    
    is_premium = user['is_premium']
    
    allocated_spot_id = None
    query_message = ""
    
    # --- Allocation Logic: Determine Target Floor ---
    target_floor = get_least_dense_floor(cursor)
    
    # 2. PREMIUM PRIORITY: Try to find the best available Premium spot on the LEAST DENSE floor
    if is_premium == 1:
        query_premium = """
            SELECT spot_id FROM ParkingSpots 
            WHERE floor = ? AND spot_type = 'Premium' AND is_occupied = 0 
            ORDER BY spot_id ASC LIMIT 1
        """
        premium_spot = cursor.execute(query_premium, (target_floor,)).fetchone()
        
        if premium_spot:
            allocated_spot_id = premium_spot['spot_id']
            query_message = f"Allocated nearest Premium spot in {target_floor} (Least Dense)."

    # 3. STANDARD/FALLBACK PRIORITY: Find the best available Standard spot on the LEAST DENSE floor
    if allocated_spot_id is None:
        query_standard = """
            SELECT spot_id FROM ParkingSpots 
            WHERE floor = ? AND spot_type = 'Standard' AND is_occupied = 0 
            ORDER BY spot_id ASC LIMIT 1
        """
        standard_spot = cursor.execute(query_standard, (target_floor,)).fetchone()
        
        if standard_spot:
            allocated_spot_id = standard_spot['spot_id']
            query_message = f"Allocated nearest Standard spot in {target_floor}."
            if is_premium == 1:
                query_message = f"Premium spots in {target_floor} are full. Allocated nearest Standard spot."
    
    # 4. OVERFLOW FALLBACK: If the least dense area is full or lacks the right spot type, search the entire system
    if allocated_spot_id is None:
        # Re-run the allocation search, but this time without filtering by floor
        
        if is_premium == 1:
            # Check for ANY available Premium spot (even on the dense floor)
            query_premium_any = """
                SELECT spot_id FROM ParkingSpots 
                WHERE spot_type = 'Premium' AND is_occupied = 0 
                ORDER BY spot_id ASC LIMIT 1
            """
            premium_spot_any = cursor.execute(query_premium_any).fetchone()
            if premium_spot_any:
                allocated_spot_id = premium_spot_any['spot_id']
                query_message = "Least dense area full. Allocated nearest available Premium spot."

        if allocated_spot_id is None:
            # Check for ANY available Standard spot (for everyone)
            query_standard_any = """
                SELECT spot_id FROM ParkingSpots 
                WHERE spot_type = 'Standard' AND is_occupied = 0 
                ORDER BY spot_id ASC LIMIT 1
            """
            standard_spot_any = cursor.execute(query_standard_any).fetchone()
            if standard_spot_any:
                allocated_spot_id = standard_spot_any['spot_id']
                query_message = "Least dense area full. Allocated nearest available Standard spot."


    # --- Execute Update ---
    
    if allocated_spot_id is not None:
        # Mark the spot as occupied
        cursor.execute(
            "UPDATE ParkingSpots SET is_occupied = 1 WHERE spot_id = ?",
            (allocated_spot_id,)
        )
        conn.commit()
        
        conn.close()
        return jsonify({
            "success": True, 
            "allocated_spot_id": allocated_spot_id, 
            "message": query_message
        })
    else:
        conn.close()
        return jsonify({"error": "All spots are currently occupied."}), 409


@app.route('/api/release', methods=['POST'])
def release_spot():
    """API to mark a spot as free (checkout)."""
    data = request.json
    spot_id = data.get('spot_id')

    if not spot_id:
        return jsonify({"error": "Spot ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check if spot is currently occupied
        spot = cursor.execute('SELECT is_occupied FROM ParkingSpots WHERE spot_id = ?', (spot_id,)).fetchone()
        
        if spot is None:
            return jsonify({"error": f"Spot ID {spot_id} does not exist."}), 404
        
        if spot['is_occupied'] == 0:
            return jsonify({"error": f"Spot {spot_id} is already free."}), 409

        # Mark the spot as free
        cursor.execute(
            "UPDATE ParkingSpots SET is_occupied = 0 WHERE spot_id = ?",
            (spot_id,)
        )
        conn.commit()
        return jsonify({"success": True, "message": f"Spot {spot_id} released."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# --- Application Setup ---

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection at the end of the request."""
    # 'g' is now correctly imported from flask
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

if __name__ == '__main__':
    # Initialize the database and reset spot status
    init_db()
    
    print("--- Starting Flask Server ---")
    print("Visit http://127.0.0.1:5000/api/spots to view raw data.")
    print("Open your index.html file to view the web application.")
    
    # Run the server
    app.run(debug=True)
from flask import g