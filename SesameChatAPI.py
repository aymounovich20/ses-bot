from flask import Flask, request, jsonify
import torch
import ollama
import os
import hashlib

# Flask app initialization
app = Flask(__name__)

# ANSI escape codes for colors (not used in the API but kept as-is from the original)
PINK = '\033[95m'
CYAN = '\033[96m'
YELLOW = '\033[93m'
NEON_GREEN = '\033[92m'
RESET_COLOR = '\033[0m'

# Paths for vault and cached embeddings
VAULT_FILE = "vault.txt"
EMBEDDINGS_FILE = "vault_embeddings.pt"
CHECKSUM_FILE = "vault_checksum.txt"

# Function to compute MD5 checksum of a file
def compute_md5(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

# Function to load embeddings and check if recalculation is needed
def load_or_generate_embeddings(vault_content):
    if os.path.exists(CHECKSUM_FILE):
        with open(CHECKSUM_FILE, "r") as f:
            saved_checksum = f.read().strip()
    else:
        saved_checksum = ""

    current_checksum = compute_md5(VAULT_FILE)

    if saved_checksum == current_checksum and os.path.exists(EMBEDDINGS_FILE):
        return torch.load(EMBEDDINGS_FILE), current_checksum

    vault_embeddings = []
    for content in vault_content:
        response = ollama.embeddings(model='mxbai-embed-large:latest', prompt=content)
        if "embedding" in response:
            vault_embeddings.append(response["embedding"])

    vault_embeddings_tensor = torch.tensor(vault_embeddings)

    # Save the embeddings and checksum
    torch.save(vault_embeddings_tensor, EMBEDDINGS_FILE)
    with open(CHECKSUM_FILE, "w") as f:
        f.write(current_checksum)

    return vault_embeddings_tensor, current_checksum

# Function to get relevant context from the vault based on user input
def get_relevant_context(user_input, vault_embeddings, vault_content, top_k=3):
    if vault_embeddings.nelement() == 0:
        return []
    input_embedding = ollama.embeddings(model='mxbai-embed-large', prompt=user_input)["embedding"]
    cos_scores = torch.cosine_similarity(torch.tensor(input_embedding).unsqueeze(0), vault_embeddings)
    top_k = min(top_k, len(cos_scores))
    top_indices = torch.topk(cos_scores, k=top_k)[1].tolist()
    return [vault_content[idx].strip() for idx in top_indices]

# Function to interact with the Ollama model
def ollama_chat(user_input, system_message, vault_embeddings, vault_content, ollama_model, conversation_history):
    relevant_context = get_relevant_context(user_input, vault_embeddings, vault_content, top_k=3)
    user_input_with_context = "\n\n".join(relevant_context) + "\n\n" + user_input if relevant_context else user_input
    conversation_history.append({"role": "user", "content": user_input_with_context})

    messages = [{"role": "system", "content": system_message}, *conversation_history]
    response = ollama.chat(model=ollama_model, messages=messages)

    if 'message' in response and 'content' in response['message']:
        conversation_history.append({"role": "assistant", "content": response['message']['content']})
    else:
        conversation_history.append({"role": "assistant", "content": "No response content."})

    return response.get('message', {}).get('content', "No response content.")

# Load the vault content
vault_content = []
if os.path.exists(VAULT_FILE):
    with open(VAULT_FILE, "r", encoding='utf-8') as vault_file:
        vault_content = vault_file.readlines()

# Load or generate embeddings
vault_embeddings_tensor, current_checksum = load_or_generate_embeddings(vault_content)

# Conversation history and system message
conversation_history = []
system_message = (
    "Vous êtes un assistant utile et bienveillant pour les étudiants de l'université SESAME. "
    "Votre rôle est de répondre de manière courte, informative et compatissante à leurs questions. "
    "Si vous ne connaissez pas la réponse, dites simplement que vous ne savez pas."
)

# API Endpoint: Health Check
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "API is running"}), 200
    
# API Endpoint: Check Ollama Status
@app.route('/ollama-status', methods=['GET'])
def ollama_status():
    try:
        # Perform a basic test request to check if Ollama is running
        response = ollama.list()
        #response2 = ollama.show()
        #print(response2)
        if response:
            return jsonify({"status": "Ollama is running"}), 200
        return jsonify({"status": "Ollama is not running or unresponsive"}), 500
    except Exception as e:
        return jsonify({"status": "Error checking Ollama", "error": str(e)}), 500

# Define the API endpoint
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_input = data.get("user_input", "")
    #ollama_model = data.get("model", "llama3.2:latest")

    if not user_input:
        return jsonify({"error": "Missing 'user_input' in request"}), 400

    response = ollama_chat(user_input, system_message, vault_embeddings_tensor, vault_content, "llama3.2:latest", conversation_history)
    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(debug=True,port=5000)