# YourPeer Chatbot

Chatbot for the YourPeer network by Streetlives.

## Goals
Provide an easy conversational interface to help the unhomed find services.

## Stack (planned)
- LLM: Claude Sonnet
- Backend: FastAPI
- Frontend: React chat component
- Database: Streetlives PostgreSQL (read-only)

## Architecture
User → Chat UI → Backend → LLM + Query Templates → Streetlives API