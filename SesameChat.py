import torch
import ollama
import os
import hashlib
import argparse

# ANSI escape codes for colors
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
        print(NEON_GREEN + "Loading cached embeddings..." + RESET_COLOR)
        return torch.load(EMBEDDINGS_FILE), current_checksum

    print(NEON_GREEN + "Generating embeddings for the vault content..." + RESET_COLOR)
    vault_embeddings = []
    for content in vault_content:
        response = ollama.embeddings(model='mxbai-embed-large:latest', prompt=content)
        if "embedding" in response:
            vault_embeddings.append(response["embedding"])
        else:
            print(f"Failed to get embeddings for: {content}")

    vault_embeddings_tensor = torch.tensor(vault_embeddings)

    # Save the embeddings and checksum
    torch.save(vault_embeddings_tensor, EMBEDDINGS_FILE)
    with open(CHECKSUM_FILE, "w") as f:
        f.write(current_checksum)

    return vault_embeddings_tensor, current_checksum

# Function to get relevant context from the vault based on user input
def get_relevant_context(rewritten_input, vault_embeddings, vault_content, top_k=3):
    if vault_embeddings.nelement() == 0:  # Check if the tensor has any elements
        return []
    # Encode the rewritten input
    input_embedding = ollama.embeddings(model='mxbai-embed-large', prompt=rewritten_input)["embedding"]
    # Compute cosine similarity between the input and vault embeddings
    cos_scores = torch.cosine_similarity(torch.tensor(input_embedding).unsqueeze(0), vault_embeddings)
    # Adjust top_k if it's greater than the number of available scores
    top_k = min(top_k, len(cos_scores))
    # Sort the scores and get the top-k indices
    top_indices = torch.topk(cos_scores, k=top_k)[1].tolist()
    # Get the corresponding context from the vault
    relevant_context = [vault_content[idx].strip() for idx in top_indices]
    return relevant_context

# Function to interact with the Ollama model
def ollama_chat(user_input, system_message, vault_embeddings, vault_content, ollama_model, conversation_history):
    # Get relevant context from the vault
    relevant_context = get_relevant_context(user_input, vault_embeddings, vault_content, top_k=3)
    if relevant_context:
        # Convert list to a single string with newlines between items
        context_str = "\n".join(relevant_context)
        print("Context Pulled from Documents: \n\n" + CYAN + context_str + RESET_COLOR)
    else:
        print(CYAN + "No relevant context found." + RESET_COLOR)
    
    # Prepare the user's input by concatenating it with the relevant context
    user_input_with_context = context_str + "\n\n" + user_input if relevant_context else user_input
    
    # Append the user's input to the conversation history
    conversation_history.append({"role": "user", "content": user_input_with_context})
    
    # Create a message history including the system message and the conversation history
    messages = [
        {"role": "system", "content": system_message},
        *conversation_history
    ]
    
    # Send the completion request to the Ollama model
    response = ollama.chat(model=ollama_model, messages=messages)
    
    # Check if the response contains a message with content
    if 'message' in response and 'content' in response['message']:
        conversation_history.append({"role": "assistant", "content": response['message']['content']})
    else:
        print("Error: 'content' key not found in response['message'].")
        conversation_history.append({"role": "assistant", "content": "No response content."})
    
    return response.get('message', {}).get('content', "No response content.")

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Ollama Chat")
parser.add_argument("--model", default="llama3.2:latest", help="Ollama model to use (default: llama3.2:latest)")
args = parser.parse_args()

# Load the vault content
vault_content = []
if os.path.exists(VAULT_FILE):
    with open(VAULT_FILE, "r", encoding='utf-8') as vault_file:
        vault_content = vault_file.readlines()

# Load or generate embeddings
vault_embeddings_tensor, current_checksum = load_or_generate_embeddings(vault_content)

# Conversation loop
conversation_history = []
system_message = (
    "Vous êtes un assistant utile et bienveillant pour les étudiants de l'université SESAME. "
    "Votre rôle est de répondre de manière courte, informative et compatissante à leurs questions. "
    "Si vous ne connaissez pas la réponse, dites simplement que vous ne savez pas."
)

while True:
    user_input = input(YELLOW + "Posez une question a Sesame chatbot: (or type 'quit' to exit): " + RESET_COLOR)
    if user_input.lower() == 'quit':
        break

    response = ollama_chat(user_input, system_message, vault_embeddings_tensor, vault_content, args.model, conversation_history)
    print(NEON_GREEN + "Response: \n\n" + response + RESET_COLOR)