from flask import Flask, session, jsonify, request # Garanta que request está importado
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import google.generativeai as genai
from dotenv import load_dotenv
import os
from uuid import uuid4

# --- Importar Config e Blueprints ---
from config import conn, cursor # Assuming config.py is correctly set up
from auth_routes import auth_bp
from freemium_routes import freemium_bp
from premium_routes import premium_bp
from admin_routes import admin_bp 
from quiz_routes import quiz_bp # <--- ADICIONE ESTA LINHA

# --- Configurações Iniciais ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "uma-chave-secreta-padrao-muito-forte")

# --- CORREÇÃO CORS ---
CORS(app,
     origins="*",  # Em produção, restrinja isso ao seu domínio frontend
     supports_credentials=True)

socketio = SocketIO(app, cors_allowed_origins="*")

# --- Configuração Google GenAI ---
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("ERRO: GOOGLE_API_KEY não encontrada no .env")
else:
    try:
        genai.configure(api_key=API_KEY)
        print("Google GenAI configurado com sucesso.")
    except Exception as e:
        print(f"ERRO ao configurar Google GenAI: {e}")

MODEL_NAME = "gemini-2.5-flash" 

# --- Registrar Blueprints (Rotas Separadas) ---
app.register_blueprint(auth_bp)
app.register_blueprint(freemium_bp)
app.register_blueprint(premium_bp)
app.register_blueprint(admin_bp) 
app.register_blueprint(quiz_bp) # <--- ADICIONE ESTA LINHA

# --- Rota Principal (Teste) ---
@app.route('/')
def index():
    return 'API ON - Estrutura Refatorada', 200

# ===================================
# Chatbot com SocketIO
# ===================================

# =====> INSTRUÇÕES DO CHAT ALTERADAS AQUI <=====
instrucoes = """Você é um tutor de Filosofia e Sociologia. Seu objetivo não é dar respostas prontas, mas sim gerar uma conversa real que faça o usuário pensar. Aja como um parceiro de debate. 

Em vez de simplesmente responder, faça perguntas de volta, desafie as premissas do usuário e incentive-o a explorar diferentes ângulos de um mesmo tema. Conduza a conversa para fora da zona de conforto, estimulando o pensamento crítico e a reflexão profunda. 

Use uma linguagem natural e acessível, como se fosse uma pessoa conversando. O objetivo é que o usuário sinta que está em um diálogo genuíno, não em um interrogatório.
"""
# ================================================

active_chats = {}

def get_user_chat():
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
    session_id = session['session_id']

    if session_id not in active_chats:
        if not API_KEY: # Verifica se a chave foi carregada
             print("Chatbot: Chave API não configurada.")
             return None
        try:
            # Não precisa configurar de novo aqui se já fez globalmente
            model = genai.GenerativeModel(MODEL_NAME)
            chat_session = model.start_chat(history=[
                {"role": "user", "parts": [{"text": instrucoes}]},
                {"role": "model", "parts": [{"text": "Olá! Estou aqui para bater um papo sobre filosofia e sociologia. Sobre o que você gostaria de conversar hoje?"}]}
            ])
            active_chats[session_id] = chat_session
            print(f"Novo chat iniciado para sessão: {session_id}")
        except Exception as e:
            print(f"Erro ao iniciar chat da IA para sessão {session_id}: {e}")
            return None
    # else: # Opcional: Log para saber se está reutilizando chat
        # print(f"Reutilizando chat para sessão: {session_id}")

    return active_chats.get(session_id) # Use .get para evitar KeyError se a criação falhar

@socketio.on('connect')
def handle_connect():
     print(f"Cliente conectado: {request.sid}")
     # Garante que uma session_id seja criada se não existir
     if 'session_id' not in session:
        session['session_id'] = str(uuid4())
        print(f"Nova session_id criada na conexão: {session['session_id']}")

     user_chat = get_user_chat() # Tenta obter/criar o chat
     if user_chat and user_chat.history: # Verifica se o chat e o histórico existem
        # Pega a última mensagem (que deve ser a de boas-vindas do bot)
        welcome_message = "Olá! Estou aqui para bater um papo sobre filosofia e sociologia. Sobre o que você gostaria de conversar hoje?"
        if user_chat.history and len(user_chat.history) > 1 and user_chat.history[-1].role == 'model':
             welcome_message = user_chat.history[-1].parts[0].text
        elif user_chat.history and user_chat.history[1].role == 'model': # Fallback para a segunda mensagem (após instrução)
             welcome_message = user_chat.history[1].parts[0].text

        emit('nova_mensagem', {"remetente": "bot", "texto": welcome_message})
        emit('status_conexao', {'data': 'Conectado com sucesso!'})
     elif not API_KEY:
         emit('erro', {'erro': 'Assistente de IA indisponível (chave não configurada).'})
     else:
        emit('erro', {'erro': 'Não foi possível iniciar o assistente de IA.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
     mensagem_usuario = data.get("mensagem")
     print(f"Mensagem recebida de {request.sid}: {mensagem_usuario}") # Log
     if not mensagem_usuario:
        emit('erro', {"erro": "Mensagem não pode ser vazia."})
        return

     user_chat = get_user_chat() # Tenta obter o chat da sessão
     if not user_chat:
        print(f"Erro: Chat não encontrado para session_id: {session.get('session_id')}") # Log
        emit('erro', {'erro': 'Chat não iniciado ou sessão perdida. Tente reconectar.'})
        return

     try:
        # Envia a mensagem para o modelo GenAI
        print(f"Enviando para IA (sessão {session.get('session_id')}): {mensagem_usuario}") # Log
        resposta = user_chat.send_message(mensagem_usuario)
        print(f"Resposta da IA (sessão {session.get('session_id')}): {resposta.text[:50]}...") # Log
        # Emite a resposta de volta para o cliente
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta.text})
     except Exception as e:
        # Log detalhado do erro no servidor
        print(f"Erro na chamada da API GenAI (sessão {session.get('session_id')}): {e}")
        # Mensagem genérica para o cliente
        emit('erro', {'erro': 'Ocorreu um erro ao processar sua mensagem com a IA. Tente novamente.'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Cliente desconectado: {request.sid}")
    # Limpa o chat ativo associado à sessão quando o usuário desconecta
    session_id = session.get('session_id') # Usa get para evitar erro se não existir
    if session_id and session_id in active_chats:
        del active_chats[session_id]
        print(f"Chat da sessão {session_id} limpo.")
    # session.pop('session_id', None) # Opcional: Limpar o ID da sessão Flask também


# --- Inicialização ---
if __name__ == "__main__":
    print("Iniciando servidor Flask com SocketIO...")
    # Use allow_unsafe_werkzeug=True apenas para desenvolvimento com debug reloader
    socketio.run(app, host="0.0.0.0", debug=True, allow_unsafe_werkzeug=True)