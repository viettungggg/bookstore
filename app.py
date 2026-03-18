from flask import Flask, request, jsonify, make_response
from dotenv import load_dotenv
import threading
import requests
import os

load_dotenv()
from db import get_conn

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
US_STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC"]

BOOK_FIELDS = ["ISBN", "title", "Author", "description", "genre", "price", "quantity"]
CUSTOMER_FIELDS = ["userId", "name", "phone", "address", "city", "state", "zipcode"]


def require_fields(data,fields):
    for f in fields:
        if f not in data or str(data[f]).strip() == "":
            return False
    return True


def valid_price(val):
    s = str(val)
    if "." in s:
        if len(s.split(".")[1])> 2:
            return False
    try:
        if float(s) < 0:
            return False
        return True
    except:
        return False


def fetch_sumary(isbn, title, author):
    try:
        prompt = f"Write a 500 word summary of the book '{title}' by {author}."
        body = {"contents": [{"parts": [{"text": prompt}]}]}

        r=requests.post(GEMINI_URL + "?key=" + GEMINI_API_KEY, json=body, timeout=36)
        result=r.json()
        summary=result["candidates"][0]["content"]["parts"][0]["text"]

        conn = get_conn()
        cur=conn.cursor()
        cur.execute("UPDATE Books SET summary = %(s)s WHERE ISBN = %(isbn)s", {"s": summary, "isbn": isbn})
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("couldnt get summary for", isbn,e)


@app.route("/books", methods=["POST"])
def add_book():
    """
    POST /books
    Add a new book. Requires ISBN, title, Author, description, genre, price, quantity.
    Returns 201 with book data, 422 if ISBN already exists, 400 for bad input.
    Also triggers a background LLM call to generate a summary.
    """
    data = request.get_json(silent=True)
    if not data or not require_fields(data,BOOK_FIELDS):
        return jsonify({"message": "Invalid or missing fields"}), 400

    if not valid_price(data["price"]):
        return jsonify({"message": "Invalid or missing fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        data["summary"] = ""
        cur.execute(
            "INSERT INTO Books (ISBN, title, Author, description, genre, price, quantity, summary) "
            "VALUES (%(ISBN)s, %(title)s, %(Author)s, %(description)s, %(genre)s, %(price)s, %(quantity)s, %(summary)s)",
            data
        )
        conn.commit()
    except Exception as e:
        if "Duplicate entry" in str(e):
            return jsonify({"message": "This ISBN already exists in the system."}), 422
        print("db error on add_book:", e)
        return jsonify({"message": "Database error"}), 500
    finally:
        cur.close()
        conn.close()

    fetch_sumary(data["ISBN"], data["title"], data["Author"])

    resp = make_response(jsonify({
        "ISBN": data["ISBN"],
        "title": data["title"],
        "Author": data["Author"],
        "description": data["description"],
        "genre": data["genre"],
        "price": data["price"],
        "quantity": data["quantity"]
    }), 201)
    resp.headers["Location"] = f"/books/{data['ISBN']}"
    return resp


@app.route("/books/<isbn>", methods=["PUT"])
def update_book(isbn):
    """
    PUT /books/<isbn>
    Update an existing book by ISBN. All fields required. ISBN in body must match URL.
    Returns 200 with updated data, 404 if not found, 400 for bad input.
    """
    data = request.get_json(silent=True)
    if not data or not require_fields(data, BOOK_FIELDS):
        return jsonify({"message": "Invalid or missing fields"}), 400

    if not valid_price(data["price"]):
        return jsonify({"message": "Invalid or missing fields"}), 400

    if data["ISBN"] != isbn:
        return jsonify({"message": "Invalid or missing fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE Books SET title=%(title)s, Author=%(Author)s, description=%(description)s, "
            "genre=%(genre)s, price=%(price)s, quantity=%(quantity)s WHERE ISBN=%(ISBN)s",
            data
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"message": "Book not found"}), 404
    except Exception as e:
        print("db error on update_book:", e)
        return jsonify({"message":"Database error"}),500
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "ISBN": isbn,
        "title": data["title"],
        "Author": data["Author"],
        "description": data["description"],
        "genre": data["genre"],
        "price": data["price"],
        "quantity": data["quantity"]
    }),200

@app.route("/books/<isbn>", methods=["GET"])
@app.route("/books/isbn/<isbn>", methods=["GET"])
def get_book(isbn):
    """
    GET /books/<isbn> or /books/isbn/<isbn>
    Retrieve a book by ISBN. Returns 200 with book data including summary, 404 if not found.
    """
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM Books WHERE ISBN = %(isbn)s", {"isbn": isbn})
        book = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not book:
        return jsonify({"message":"Book not found"}), 404
    book["price"] = float(book["price"])
    return jsonify(book),200


@app.route("/customers", methods=["POST"])
def add_customer():
    """
    POST /customers
    Register a new customer. Requires userId, name, phone, address, city, state, zipcode.
    address2 is optional. Returns 201 with customer data and generated id, 422 if userId exists.
    """
    data = request.get_json(silent=True)
    if not data or not require_fields(data, CUSTOMER_FIELDS):
        return jsonify({"message": "Invalid or missing fields"}), 400

    email = data["userId"]
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"message": "Invalid or missing fields"}), 400

    if data["state"] not in US_STATES:
        return jsonify({"message": "Invalid or missing fields"}), 400

    if "address2" not in data:
        data["address2"] = None

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO Customers (userId, name, phone, address, address2, city, state, zipcode) "
            "VALUES (%(userId)s, %(name)s, %(phone)s, %(address)s, %(address2)s, %(city)s, %(state)s, %(zipcode)s)",
            data
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception as e:
        if "Duplicate entry" in str(e):
            return jsonify({"message": "This user ID already exists in the system."}), 422
        print("db error on add_customer:", e)
        return jsonify({"message": "Database error"}), 500
    finally:
        cur.close()
        conn.close()

    resp = make_response(jsonify({
        "id": new_id,
        "userId": data["userId"],
        "name": data["name"],
        "phone": data["phone"],
        "address": data["address"],  
        "address2": data["address2"], 
        "city": data["city"],
        "state": data["state"],
        "zipcode": data["zipcode"]
    }), 201)
    resp.headers["Location"] = f"/customers/{new_id}"
    return resp


@app.route("/customers", methods=["GET"])
def get_customer_by_userid():
    """
    GET /customers?userId=<email>
    Retrieve a customer by their userId (email). Returns 200 with data, 404 if not found.
    """
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"message": "Missing userId"}),400
    if "@" not in user_id or "." not in user_id.split("@")[-1]:
        return jsonify({"message": "Invalid userId"}), 400

    conn = get_conn()
    cur = conn.cursor( dictionary = True) 
    try:
        cur.execute("SELECT * FROM Customers WHERE userId = %(uid)s", {"uid":user_id})
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        return jsonify({"message":"Customer not found"}),404
    return jsonify(row), 200


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    """
    GET /customers/<id>
    Retrieve a customer by numeric ID. Returns 200 with data, 404 if not found, 400 if ID is not a number.
    """
    try:
        cid = int(cid)
    except:
        return jsonify({"message": "Invalid ID"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM Customers WHERE id = %(id)s", {"id": cid})
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        return jsonify({"message": "Customer not found"}), 404
    return jsonify(row), 200


@app.route("/status")
def status():
    resp = make_response("OK",200)
    resp.headers["Content-Type"] = "text/plain"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
