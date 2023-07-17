'''
Created on 17 Jul 2023

@author: franco
'''

import argparse
import re
import time
import feedparser
import sqlite3
from flask import Flask, Response, render_template, request, current_app
from os import path

wservice = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    with wservice.app_context():
        conn = get_db_connection()
        c = conn.cursor()

        # Création de la table "feeds" si elle n'existe pas
        c.execute('''CREATE TABLE IF NOT EXISTS feeds
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      url TEXT NOT NULL)''')

        # Création de la table "regex" si elle n'existe pas
        c.execute('''CREATE TABLE IF NOT EXISTS regex
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      feed_id INTEGER,
                      pattern TEXT,
                      FOREIGN KEY (feed_id) REFERENCES feeds(id))''')

        # Création de la table "users" si elle n'existe pas
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      api_key TEXT NOT NULL)''')

        # Création de la table "user_feeds" si elle n'existe pas
        c.execute('''CREATE TABLE IF NOT EXISTS user_feeds
                     (user_id INTEGER,
                      feed_id INTEGER,
                      FOREIGN KEY (user_id) REFERENCES users(id),
                      FOREIGN KEY (feed_id) REFERENCES feeds(id))''')

        conn.commit()
        conn.close()

def get_feeds():
    conn = get_db_connection()
    c = conn.cursor()

    # Récupération de tous les flux de la base de données avec les expressions régulières associées
    c.execute("SELECT feeds.id, feeds.url, GROUP_CONCAT(regex.pattern, '|') AS regex_patterns FROM feeds LEFT JOIN regex ON feeds.id = regex.feed_id GROUP BY feeds.id")
    feeds = c.fetchall()

    conn.close()

    return feeds

def add_feed(url, regex_patterns=None):
    conn = get_db_connection()
    c = conn.cursor()

    # Insertion du flux dans la base de données
    c.execute("INSERT INTO feeds (url) VALUES (?)", (url,))
    feed_id = c.lastrowid

    if regex_patterns:
        regex_values = [(feed_id, pattern) for pattern in regex_patterns]
        c.executemany("INSERT INTO regex (feed_id, pattern) VALUES (?, ?)", regex_values)

    conn.commit()
    conn.close()

def remove_old_entries():
    conn = get_db_connection()
    c = conn.cursor()

    # Suppression des entrées plus anciennes d'une semaine
    timestamp = time.time() - (7 * 24 * 60 * 60)  # 7 jours en secondes
    c.execute("DELETE FROM feeds WHERE id IN (SELECT id FROM feeds WHERE strftime('%s', datetime('now')) - strftime('%s', timestamp) > ?)", (timestamp,))
    conn.commit()

    conn.close()

def add_user(api_key):
    conn = get_db_connection()
    c = conn.cursor()

    # Insertion de l'utilisateur dans la base de données
    c.execute("INSERT INTO users (api_key) VALUES (?)", (api_key,))
    conn.commit()

    conn.close()

def get_user(api_key):
    conn = get_db_connection()
    c = conn.cursor()

    # Récupération de l'utilisateur à partir de la clé API
    c.execute("SELECT * FROM users WHERE api_key=?", (api_key,))
    user = c.fetchone()

    conn.close()

    return user

def get_user_feeds(api_key):
    conn = get_db_connection()
    c = conn.cursor()

    # Récupération des flux de l'utilisateur à partir de la clé API
    c.execute("SELECT feeds.id, feeds.url, GROUP_CONCAT(regex.pattern, '|') AS regex_patterns FROM feeds JOIN user_feeds ON feeds.id = user_feeds.feed_id LEFT JOIN regex ON feeds.id = regex.feed_id WHERE user_feeds.user_id = (SELECT id FROM users WHERE api_key=?) GROUP BY feeds.id", (api_key,))
    feeds = c.fetchall()

    conn.close()

    return feeds

def add_user_feed(api_key, feed_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Insertion de la relation utilisateur-flux dans la base de données
    c.execute("INSERT INTO user_feeds (user_id, feed_id) VALUES ((SELECT id FROM users WHERE api_key=?), ?)", (api_key, feed_id))
    conn.commit()

    conn.close()

def remove_user_feed(api_key, feed_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Suppression de la relation utilisateur-flux de la base de données
    c.execute("DELETE FROM user_feeds WHERE user_id=(SELECT id FROM users WHERE api_key=?) AND feed_id=?", (api_key, feed_id))
    conn.commit()

    conn.close()

@wservice.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        url = request.form.get('url')
        regex_patterns = request.form.get('regex_patterns').splitlines() if request.form.get('regex_patterns') else None

        if url:
            add_feed(url, regex_patterns)

    feeds = get_feeds()

    return render_template('home.html', feeds=feeds)

@wservice.route('/api/<api_key>/feeds', methods=['GET'])
def api_feeds(api_key):
    user = get_user(api_key)

    if user:
        user_feeds = get_user_feeds(api_key)
        feed_entries = []

        for feed in user_feeds:
            url = feed['url']
            regex_patterns = feed['regex_patterns'].split('|') if feed['regex_patterns'] else None
            feed_data = feedparser.parse(url)

            for entry in feed_data.entries:
                if regex_patterns:
                    for pattern in regex_patterns:
                        if re.search(pattern, entry.title):
                            feed_entries.append(entry)
                            break
                else:
                    feed_entries.append(entry)

        # Supprimer les entrées plus anciennes d'une semaine
        remove_old_entries()

        # Trier les entrées par date de publication (du plus récent au plus ancien)
        sorted_entries = sorted(feed_entries, key=lambda x: x.published_parsed, reverse=True)

        # Créer le flux de fusion pour l'utilisateur
        user_feed = feedparser.FeedParserDict()
        user_feed.feed = {
            'title': 'Flux Fusionné pour l\'utilisateur {}'.format(api_key),
            'link': 'https://example.com/api/{}/feeds'.format(api_key),
            'description': 'Ce flux est une fusion de vos flux Atom et RSS',
        }
        user_feed.entries = sorted_entries

        # Générer le XML du flux de fusion pour l'utilisateur
        xml = user_feed.to_xml()

        # Retourner le flux en tant que réponse HTTP avec le bon en-tête
        return Response(xml, mimetype='application/atom+xml')

    else:
        # Clé API invalide
        return Response(status=401)

@wservice.route('/api/<api_key>/feeds/<feed_id>', methods=['PUT', 'DELETE'])
def api_user_feed(api_key, feed_id):
    user = get_user(api_key)

    if user:
        if request.method == 'PUT':
            add_user_feed(api_key, feed_id)

        elif request.method == 'DELETE':
            remove_user_feed(api_key, feed_id)

        return Response(status=204)  # Réponse sans contenu (succès)

    else:
        # Clé API invalide
        return Response(status=401)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='This script clean your feeds', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-o","--out", metavar='outdir', type=str, default=".", help="Folder where send the database")
    parser.add_argument("--tmp", metavar='tmpdir', type=str,
                        default="/tmp", help="Folder where send temporar files")
    parser.add_argument("--pwd", metavar='pwd', type=str,
                        default=".", help="Path to the software, put it if you use the folder from another folder")
    parser.add_argument("-p","--port", metavar='port', type=int, default=5050, help="Port use")
    parser.add_argument("--dev", dest='dev', default=False, action='store_true', help="Print more errors and write all logs")
    args = parser.parse_args()
    
    # Chemin vers la base de données SQLite
    wservice.config['DATABASE'] = path.join(args.out,'pyFeedsSeletor.db')
    
    initialize_database()
    wservice.run(port=args.port, debug=args.dev) #host='127.0.0.1',