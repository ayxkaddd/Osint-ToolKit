# OSINT Toolkit

A modern web interface for various OSINT tools and resources. Built with FastAPI, TailwindCSS, and a focus on user experience.

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
git clone https://github.com/yourusername/osint-toolkit.git
cd osint-toolkit
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your configuration:
```env
GITFIVE_VENV_PATH=/path/to/gitfive/venv/bin/python
GITFIVE_SCRIPT_PATH=/path/to/GitFive/main.py
OSINT_INDUSTRIES_API_KEY=your_api_key_here
```

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
