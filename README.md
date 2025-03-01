# OSINT Toolkit

A modern web interface for various OSINT tools and resources. Built with FastAPI, TailwindCSS, and a focus on user experience.

## Preview

![preview](https://github.com/user-attachments/assets/56aa5659-461a-4c97-af07-6abb857aa5d9)

## Features

- **GitHub Analysis**: Deep dive into GitHub profiles using GitFive
- **DNS Lookup**: Find shared nameservers and domain relationships
- **OSINT Industries Integration**: Search for emails, phones, and usernames
- **Cavalier API**: Search for compromised accounts and data
- **DoxBin Search**: Search the breached DoxBin database
- **WHOIS History**: Research domain registration history
- **External Resources**: Curated list of useful OSINT tools and websites

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ayxkaddd/Osint-ToolKit
cd Osint-ToolKit
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the project and its dependencies:
```bash
pip install .
```

4. Create a `.env` file with your configuration:
```env
JWT_SECRET=your_jwt_secret_key
ROOT_EMAIL=your_email@example.com
ROOT_PASSWORD=your_password_encrypted_with_bcrypt
```

You can configure other variables in the web interface.

## Usage

1. Start the FastAPI server:
```bash
uvicorn main:app --reload
```

2. Open your browser and navigate to `http://localhost:8000`

## Project Structure

- `/assets`: Static files and cached results
- `/models`: Pydantic models for data validation
- `/routes`: API route handlers
- `/services`: Business logic and external service integrations
- `/templates`: HTML templates using TailwindCSS

## Features in Detail

### GitHub Analysis
Uses GitFive to analyze GitHub profiles, including:
- Repository statistics
- Contribution patterns
- Email addresses
- SSH keys
- Related accounts

### DNS Lookup
Analyzes nameserver relationships:
- Finds domains sharing nameservers
- Bulk WHOIS lookups
- Domain relationship visualization

### External Resources
Provides quick access to popular OSINT tools:
- Domain research tools
- Public bucket searchers
- Breach databases
- OSINT search engines
