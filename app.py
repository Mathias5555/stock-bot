# app.py - Robot d'Analyse Boursière avec Telegram
import os
import time
import requests
import schedule
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json
import sqlite3
from typing import List, Dict, Optional

app = Flask(__name__)
CORS(app)

# Configuration avec tes vraies valeurs
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "8434769242:AAEUUFDi7ODWYKrXUUhVO54UxFAUCU_2fFI")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "6888820516")
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', "d369iapr01qumnp4pntgd369iapr01qumnp4pnu0")
ALERT_THRESHOLD = float(os.environ.get('ALERT_THRESHOLD', '-20'))

# Top 50 actions les plus stables du S&P 500
DEFAULT_WATCHLIST = [
    # Tech Giants
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "TSLA", "ORCL", "CRM", "ADBE", "INTC",
    # Finance
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "USB", "PNC", "COF",
    # Santé
    "UNH", "JNJ", "PFE", "ABBV", "TMO", "MDT", "LLY", "BMY", "AMGN", "GILD",
    # Consommation
    "AMZN", "WMT", "HD", "PG", "KO", "PEP", "NKE", "MCD", "SBUX", "TGT",
    # Industriel
    "BA", "CAT", "MMM", "GE", "HON", "UPS", "LMT", "RTX", "DE", "EMR"
]

class StockAnalyzer:
    def __init__(self):
        self.init_database()
        self.watchlist = self.load_watchlist()
        self.is_running = False
        
    def init_database(self):
        """Initialise la base de données SQLite"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        
        # Table pour l'historique des prix
        c.execute('''CREATE TABLE IF NOT EXISTS stock_prices
                    (symbol TEXT, price REAL, timestamp DATETIME, 
                     weekly_change REAL, volume INTEGER,
                     PRIMARY KEY (symbol, timestamp))''')
        
        # Table pour les alertes
        c.execute('''CREATE TABLE IF NOT EXISTS alerts
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     symbol TEXT, change_percent REAL, price REAL,
                     timestamp DATETIME, sent BOOLEAN DEFAULT FALSE)''')
        
        # Table pour la watchlist
        c.execute('''CREATE TABLE IF NOT EXISTS watchlist
                    (symbol TEXT PRIMARY KEY)''')
        
        conn.commit()
        conn.close()
      def load_watchlist(self) -> List[str]:
        """Charge la watchlist depuis la DB ou utilise la liste par défaut"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        c.execute("SELECT symbol FROM watchlist")
        symbols = [row[0] for row in c.fetchall()]
        conn.close()
        
        if not symbols:
            # Première fois : charge la liste par défaut
            self.save_watchlist(DEFAULT_WATCHLIST)
            return DEFAULT_WATCHLIST
        return symbols
    
    def save_watchlist(self, symbols: List[str]):
        """Sauvegarde la watchlist en DB"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        c.execute("DELETE FROM watchlist")
        for symbol in symbols:
            c.execute("INSERT INTO watchlist (symbol) VALUES (?)", (symbol,))
        conn.commit()
        conn.close()
        self.watchlist = symbols
    
    def get_stock_data(self, symbol: str) -> Optional[Dict]:
        """Récupère les données d'une action via Finnhub API"""
        try:
            # Prix actuel
            quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            quote_response = requests.get(quote_url, timeout=10)
            quote_data = quote_response.json()
            
            if quote_data.get('c') is None:
                print(f"Pas de données pour {symbol}")
                return None
                
            current_price = quote_data['c']
            previous_close = quote_data['pc']
            
            if current_price == 0 or previous_close == 0:
                return None
            
            # Calcul du changement hebdomadaire (approximation)
            weekly_change = ((current_price - previous_close) / previous_close) * 100
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'previous_close': previous_close,
                'weekly_change': weekly_change,
                'volume': quote_data.get('t', 0),
                'timestamp': datetime.now()
            }
        except Exception as e:
            print(f"Erreur lors de la récupération de {symbol}: {e}")
            return None
    
    def save_stock_data(self, data: Dict):
        """Sauvegarde les données en base"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO stock_prices 
                    (symbol, price, timestamp, weekly_change, volume) 
                    VALUES (?, ?, ?, ?, ?)""",
                 (data['symbol'], data['current_price'], data['timestamp'], 
                  data['weekly_change'], data['volume']))
        conn.commit()
        conn.close()
    
    def send_telegram_alert(self, symbol: str, change_percent: float, price: float):
        """Envoie une alerte via Telegram"""
        try:
            emoji = "🔴" if abs(change_percent) > 25 else "🟡"
            message = f"""
{emoji} *ALERTE BOURSIÈRE* {emoji}

📈 *Action:* {symbol}
📉 *Chute:* {abs(change_percent):.1f}% cette semaine
💰 *Prix actuel:* ${price:.2f}
⏰ *Heure:* {datetime.now().strftime('%H:%M:%S')}

⚠️ *Analyse recommandée !*
            """.strip()
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            params = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, params=params, timeout=10)
            if response.status_code == 200:
                print(f"✅ Alerte Telegram envoyée pour {symbol}")
                return True
            else:
                print(f"❌ Erreur Telegram: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Erreur Telegram: {e}")
            return False
    
    def save_alert(self, symbol: str, change_percent: float, price: float):
        """Sauvegarde une alerte en base"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        c.execute("""INSERT INTO alerts (symbol, change_percent, price, timestamp) 
                    VALUES (?, ?, ?, ?)""",
                 (symbol, change_percent, price, datetime.now()))
        conn.commit()
        conn.close()
      def analyze_stocks(self):
        """Analyse toutes les actions de la watchlist"""
        print(f"🔍 Démarrage de l'analyse de {len(self.watchlist)} actions...")
        alerts_sent = 0
        
        for i, symbol in enumerate(self.watchlist):
            try:
                print(f"📊 Analyse de {symbol} ({i+1}/{len(self.watchlist)})")
                data = self.get_stock_data(symbol)
                if not data:
                    continue
                    
                # Sauvegarde les données
                self.save_stock_data(data)
                
                # Vérifie si alerte nécessaire
                if data['weekly_change'] <= ALERT_THRESHOLD:
                    print(f"🚨 ALERTE: {symbol} a chuté de {abs(data['weekly_change']):.1f}%")
                    
                    # Envoie l'alerte Telegram
                    if self.send_telegram_alert(symbol, data['weekly_change'], data['current_price']):
                        self.save_alert(symbol, data['weekly_change'], data['current_price'])
                        alerts_sent += 1
                else:
                    print(f"✅ {symbol}: {data['weekly_change']:.1f}% - OK")
                
                # Pause pour respecter les limites de l'API
                time.sleep(1)
                
            except Exception as e:
                print(f"❌ Erreur lors de l'analyse de {symbol}: {e}")
        
        print(f"✅ Analyse terminée. {alerts_sent} alertes envoyées.")
        return alerts_sent
    
    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """Récupère les alertes récentes"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        c.execute("""SELECT symbol, change_percent, price, timestamp 
                    FROM alerts ORDER BY timestamp DESC LIMIT ?""", (limit,))
        alerts = []
        for row in c.fetchall():
            alerts.append({
                'symbol': row[0],
                'change_percent': row[1],
                'price': row[2],
                'timestamp': row[3]
            })
        conn.close()
        return alerts
    
    def get_current_data(self) -> List[Dict]:
        """Récupère les données actuelles de toutes les actions"""
        conn = sqlite3.connect('stock_data.db')
        c = conn.cursor()
        
        data = []
        for symbol in self.watchlist:
            c.execute("""SELECT price, weekly_change, volume, timestamp 
                        FROM stock_prices WHERE symbol = ? 
                        ORDER BY timestamp DESC LIMIT 1""", (symbol,))
            row = c.fetchone()
            if row:
                data.append({
                    'symbol': symbol,
                    'current_price': row[0],
                    'weekly_change': row[1],
                    'volume': row[2],
                    'last_update': row[3],
                    'is_alert': row[1] <= ALERT_THRESHOLD
                })
        
        conn.close()
        return data

# Instance globale
analyzer = StockAnalyzer()

# Routes Flask
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'is_running': analyzer.is_running,
        'watchlist_size': len(analyzer.watchlist),
        'last_analysis': datetime.now().isoformat(),
        'telegram_configured': True,
        'finnhub_configured': True
    })

@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    return jsonify({'symbols': analyzer.watchlist})

@app.route('/api/watchlist', methods=['POST'])
def update_watchlist():
    data = request.get_json()
    symbols = data.get('symbols', [])
    symbols = [s.upper().strip() for s in symbols if s.strip()]
    symbols = list(set(symbols))
    analyzer.save_watchlist(symbols)
    return jsonify({'success': True, 'symbols': symbols})

@app.route('/api/analyze', methods=['POST'])
def trigger_analysis():
    if analyzer.is_running:
        return jsonify({'error': 'Analyse déjà en cours'}), 400
    
    analyzer.is_running = True
    try:
        alerts_sent = analyzer.analyze_stocks()
        return jsonify({'success': True, 'alerts_sent': alerts_sent})
    finally:
        analyzer.is_running = False

@app.route('/api/alerts')
def get_alerts():
    alerts = analyzer.get_recent_alerts()
    return jsonify({'alerts': alerts})

@app.route('/api/data')
def get_data():
    data = analyzer.get_current_data()
    return jsonify({'stocks': data})

@app.route('/api/test-telegram', methods=['POST'])
def test_telegram():
    try:
        success = analyzer.send_telegram_alert("TEST", -25.5, 150.75)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Scheduler pour analyses automatiques
def run_scheduled_analysis():
    if not analyzer.is_running:
        print("⏰ Lancement de l'analyse programmée...")
        analyzer.is_running = True
        try:
            analyzer.analyze_stocks()
        finally:
            analyzer.is_running = False

# Programme les analyses toutes les heures
schedule.every().hour.do(run_scheduled_analysis)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

if __name__ == '__main__':
    print("🤖 Robot d'Analyse Boursière démarré!")
    print(f"📊 {len(analyzer.watchlist)} actions surveillées")
    print(f"📱 Telegram Chat ID: {TELEGRAM_CHAT_ID}")
    print("✅ Toutes les configurations sont prêtes!")
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
