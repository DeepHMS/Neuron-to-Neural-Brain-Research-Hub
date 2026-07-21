import os
import json
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import gspread
import feedparser

app = FastAPI(title="Neuron to Neural - Bharat Brain Research Hub")

# -----------------------------------------------------------------------------
# Google Sheets Setup
# -----------------------------------------------------------------------------
def get_gspread_client():
    try:
        secret_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if not secret_json:
            return None
        creds_dict = json.loads(secret_json)
        return gspread.service_account_from_dict(creds_dict)
    except Exception as e:
        print(f"GSpread Error: {e}")
        return None

# -----------------------------------------------------------------------------
# Pydantic Schemas & Globals
# -----------------------------------------------------------------------------
class UserAuth(BaseModel):
    name: str
    institution: str
    country: str
    email: str

class ToolItem(BaseModel):
    name: str
    category: str
    description: str
    link: str
    repo_link: Optional[str] = ""
    reference: Optional[str] = ""
    icon: Optional[str] = "🧠"

ADMIN_EMAILS = ["deeptarupbiswas2020@gmail.com"]

SAMPLE_TOOLS = [
    {
        "id": "1",
        "name": "FLEXI-Fold",
        "category": "Structural Mapping",
        "description": "Integration tool connecting mass spectrometry proteomics with 3D protein structural coordinates.",
        "link": "#",
        "repo_link": "https://github.com",
        "reference": "https://doi.org",
        "icon": "🧬",
        "stars": 4.8
    }
]

SAMPLE_NRI = [
    {"type": "Center", "name": "National Brain Research Centre (NBRC)", "location": "Manesar, Haryana", "link": "https://www.nbrc.ac.in"},
    {"type": "Lab", "name": "IIT Bombay Computational Neurobiology Lab", "location": "Mumbai, Maharashtra", "link": "https://www.iitb.ac.in"}
]

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@app.post("/api/login")
async def login_user(user: UserAuth):
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Users")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([timestamp, user.name, user.institution, user.country, user.email])
        except Exception as e:
            print(f"Error appending to sheet: {e}")
    
    is_admin = user.email in ADMIN_EMAILS
    return {"status": "success", "email": user.email, "is_admin": is_admin}

@app.get("/api/tools")
async def get_tools():
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Tools")
            records = sheet.get_all_records()
            if records:
                return {"tools": records}
        except Exception as e:
            print(f"Error fetching tools from Sheet: {e}")
            
    return {"tools": SAMPLE_TOOLS}

@app.post("/api/admin/add-tool")
async def add_tool(tool: ToolItem, request: Request):
    user_email = request.headers.get("X-User-Email")
    if user_email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Unauthorized Admin access")
    
    new_entry = tool.dict()
    new_entry["id"] = str(len(SAMPLE_TOOLS) + 1)
    new_entry["stars"] = 5.0
    
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Tools")
            sheet.append_row([
                tool.name, tool.category, tool.description, 
                tool.link, tool.repo_link, tool.reference, tool.icon, new_entry["stars"]
            ])
        except Exception as e:
            print(f"Error saving tool to Sheet: {e}")
            
    return {"status": "success", "tool": new_entry}

@app.get("/api/nri")
async def get_nri():
    return {"directory": SAMPLE_NRI}

@app.get("/api/news")
async def get_news():
    try:
        feed = feedparser.parse("https://news.yahoo.com/rss/science")
        articles = []
        for entry in feed.entries[:8]:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "published": getattr(entry, 'published', 'Recently'),
                "source": "Yahoo Science"
            })
        return {"articles": articles}
    except Exception as e:
        return {"articles": [], "error": str(e)}

# -----------------------------------------------------------------------------
# Frontend HTML/JS Route
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_content = """
<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-900 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neuron to Neural | Bharat Brain Research Hub</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="h-full flex flex-col font-sans antialiased selection:bg-indigo-500 selection:text-white">

    <!-- Auth Modal Overlay -->
    <div id="authModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
        <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 sm:p-8 max-w-md w-full shadow-2xl">
            <div class="text-center mb-6">
                <div class="w-12 h-12 bg-indigo-600/20 text-indigo-400 rounded-full flex items-center justify-center mx-auto mb-3 text-2xl">🧠</div>
                <h2 class="text-2xl font-bold text-white">Neuron to Neural</h2>
                <p class="text-xs text-indigo-400 font-medium tracking-wide uppercase mt-1">Bharat Brain Research Hub</p>
            </div>
            
            <form id="loginForm" onsubmit="handleLogin(event)" class="space-y-4">
                <div>
                    <label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Full Name *</label>
                    <input type="text" id="userName" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Institution / Company *</label>
                    <input type="text" id="userInst" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Country *</label>
                        <input type="text" id="userCountry" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Valid Email *</label>
                        <input type="email" id="userEmail" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                </div>
                <div class="flex items-start gap-2 pt-2">
                    <input type="checkbox" id="userAgree" required class="mt-1 rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500">
                    <label for="userAgree" class="text-xs text-slate-400 leading-snug">I agree to session usage for NCBI API compliance and platform updates.</label>
                </div>
                <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-2.5 rounded-lg text-sm transition shadow-lg shadow-indigo-600/30">Enter Access Portal</button>
            </form>
        </div>
    </div>

    <!-- Main Navigation Header -->
    <header class="bg-slate-800/80 backdrop-blur border-b border-slate-700 sticky top-0 z-30">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center space-x-3">
                    <span class="text-3xl">🧠</span>
                    <div>
                        <h1 class="text-lg font-bold text-white leading-tight">Neuron to Neural</h1>
                        <p class="text-xs text-indigo-400 font-medium">Bharat Brain Research Hub</p>
                    </div>
                </div>
                <div class="flex items-center space-x-2">
                    <span id="userBadge" class="hidden sm:inline-block text-xs bg-slate-700 text-slate-300 px-3 py-1 rounded-full border border-slate-600"></span>
                    <button id="adminBtn" onclick="openAdminModal()" class="hidden bg-amber-600/20 text-amber-400 border border-amber-500/40 hover:bg-amber-600/30 text-xs px-3 py-1 rounded-full font-semibold transition">
                        <i class="fa-solid fa-lock mr-1"></i> Admin
                    </button>
                </div>
            </div>
            
            <nav class="flex space-x-1 sm:space-x-4 border-t border-slate-700/50 overflow-x-auto py-2 text-xs sm:text-sm">
                <button onclick="switchTab('nue')" id="tab-nue" class="tab-btn px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700/50 whitespace-nowrap">NUE-Hub</button>
                <button onclick="switchTab('nri')" id="tab-nri" class="tab-btn px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700/50 whitespace-nowrap">NRI Directory</button>
                <button onclick="switchTab('gnn')" id="tab-gnn" class="tab-btn px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700/50 whitespace-nowrap">Global News</button>
                <button onclick="switchTab('stats')" id="tab-stats" class="tab-btn px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700/50 whitespace-nowrap">Platform Stats</button>
            </nav>
        </div>
    </header>

    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        
        <!-- Tab 1: NUE-Hub -->
        <section id="section-nue" class="tab-content space-y-6">
            <div class="flex flex-col md:flex-row gap-4 justify-between items-start md:items-center bg-slate-800/50 p-4 rounded-xl border border-slate-700/60">
                <div class="relative w-full md:w-96">
                    <i class="fa-solid fa-search absolute left-3 top-3 text-slate-400 text-sm"></i>
                    <input type="text" id="toolSearch" oninput="filterTools()" placeholder="Search tools by name, description..." class="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-indigo-500">
                </div>
                <div class="flex items-center gap-2 overflow-x-auto w-full md:w-auto text-xs">
                    <button onclick="filterCategory('All')" class="cat-chip bg-indigo-600 text-white px-3 py-1.5 rounded-lg whitespace-nowrap font-medium">All</button>
                    <button onclick="filterCategory('Omics')" class="cat-chip bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700">Omics</button>
                    <button onclick="filterCategory('Structural Mapping')" class="cat-chip bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700">Structural</button>
                    <button onclick="filterCategory('EEG')" class="cat-chip bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700">EEG / ECG</button>
                    <button onclick="filterCategory('MRI')" class="cat-chip bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700">MRI</button>
                </div>
            </div>
            <div id="toolsGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"></div>
        </section>

        <!-- Tab 2: NRI Directory -->
        <section id="section-nri" class="tab-content hidden space-y-6">
            <div class="bg-slate-800/40 p-6 rounded-xl border border-slate-700/60">
                <h2 class="text-xl font-bold text-white mb-2">Neuroscience Research in India (NRI)</h2>
            </div>
            <div id="nriGrid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </section>

        <!-- Tab 3: News -->
        <section id="section-gnn" class="tab-content hidden space-y-6">
            <div class="bg-slate-800/40 p-6 rounded-xl border border-slate-700/60">
                <h2 class="text-xl font-bold text-white mb-1">Global Neuroscience News (GNN)</h2>
            </div>
            <div id="newsGrid" class="space-y-3"></div>
        </section>

        <!-- Tab 4: Stats -->
        <section id="section-stats" class="tab-content hidden space-y-6">
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div class="bg-slate-800 border border-slate-700 rounded-xl p-5 text-center">
                    <p class="text-xs text-slate-400 font-medium uppercase">Catalogued Tools</p>
                    <p class="text-3xl font-extrabold text-indigo-400 mt-1" id="statTools">0</p>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-xl p-5 text-center">
                    <p class="text-xs text-slate-400 font-medium uppercase">NRI Centers Listed</p>
                    <p class="text-3xl font-extrabold text-indigo-400 mt-1" id="statNri">0</p>
                </div>
            </div>
        </section>

    </main>

    <!-- Admin Modal -->
    <div id="adminModal" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
        <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 max-w-lg w-full">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-bold text-white">Add New Tool</h3>
                <button onclick="closeAdminModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-times"></i></button>
            </div>
            <form id="addToolForm" onsubmit="handleAddTool(event)" class="space-y-3">
                <input type="text" id="adminToolName" placeholder="Tool Name *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                <select id="adminCategory" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300">
                    <option value="Omics">Omics</option>
                    <option value="Structural Mapping">Structural Mapping</option>
                    <option value="Digital Health">Digital Health</option>
                    <option value="EEG">EEG / ECG</option>
                    <option value="MRI">MRI</option>
                </select>
                <textarea id="adminDesc" placeholder="Description *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm h-20"></textarea>
                <input type="url" id="adminLink" placeholder="Access Link *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                <input type="url" id="adminRepo" placeholder="GitHub Repo URL" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                <input type="text" id="adminRef" placeholder="DOI / Link" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                <input type="text" id="adminIcon" placeholder="Icon Emoji (e.g., 🧬)" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm" value="🧠">
                <button type="submit" class="w-full bg-amber-600 hover:bg-amber-500 text-white font-semibold py-2 rounded-lg text-sm transition">Publish Tool</button>
            </form>
        </div>
    </div>

    <!-- Scripts -->
    <script>
        let currentUser = null;
        let allTools = [];
        let selectedCategory = 'All';

        window.addEventListener('DOMContentLoaded', () => {
            const savedUser = localStorage.getItem('n2n_user');
            if (savedUser) {
                currentUser = JSON.parse(savedUser);
                document.getElementById('authModal').classList.add('hidden');
                setupUserUI();
            }
            fetchTools();
            fetchNRI();
            fetchNews();
            switchTab('nue');
        });

        async function handleLogin(e) {
            e.preventDefault();
            const payload = {
                name: document.getElementById('userName').value,
                institution: document.getElementById('userInst').value,
                country: document.getElementById('userCountry').value,
                email: document.getElementById('userEmail').value
            };

            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            currentUser = { ...payload, is_admin: data.is_admin };
            localStorage.setItem('n2n_user', JSON.stringify(currentUser));
            document.getElementById('authModal').classList.add('hidden');
            setupUserUI();
        }

        function setupUserUI() {
            if (!currentUser) return;
            const badge = document.getElementById('userBadge');
            badge.innerText = `${currentUser.name}`;
            badge.classList.remove('hidden');

            if (currentUser.is_admin) {
                document.getElementById('adminBtn').classList.remove('hidden');
            }
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => {
                el.classList.remove('bg-indigo-600', 'text-white');
                el.classList.add('text-slate-300');
            });
            document.getElementById(`section-${tabId}`).classList.remove('hidden');
            const activeBtn = document.getElementById(`tab-${tabId}`);
            activeBtn.classList.add('bg-indigo-600', 'text-white');
            activeBtn.classList.remove('text-slate-300');
        }

        async function fetchTools() {
            const res = await fetch('/api/tools');
            const data = await res.json();
            allTools = data.tools;
            document.getElementById('statTools').innerText = allTools.length;
            renderTools(allTools);
        }

        function renderTools(tools) {
            const grid = document.getElementById('toolsGrid');
            grid.innerHTML = tools.map(t => `
                <div class="bg-slate-800/80 border border-slate-700/80 p-5 rounded-xl flex flex-col justify-between">
                    <div>
                        <div class="flex items-center justify-between mb-3">
                            <span class="text-2xl">${t.icon || '🧠'}</span>
                            <span class="text-[10px] font-semibold uppercase bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full">${t.category}</span>
                        </div>
                        <h3 class="font-bold text-white text-base">${t.name}</h3>
                        <p class="text-xs text-slate-400 mt-2 leading-relaxed">${t.description}</p>
                    </div>
                    <div class="mt-4 pt-3 border-t border-slate-700/50 flex justify-between items-center text-xs">
                        <span class="text-amber-400 font-semibold"><i class="fa-solid fa-star"></i> ${t.stars || '5.0'}</span>
                        <a href="${t.link}" target="_blank" class="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1 rounded-md">Access Tool</a>
                    </div>
                </div>
            `).join('');
        }

        function filterCategory(cat) {
            selectedCategory = cat;
            document.querySelectorAll('.cat-chip').forEach(btn => {
                if (btn.innerText.includes(cat) || (cat === 'All' && btn.innerText === 'All')) {
                    btn.className = "cat-chip bg-indigo-600 text-white px-3 py-1.5 rounded-lg whitespace-nowrap font-medium";
                } else {
                    btn.className = "cat-chip bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700";
                }
            });
            filterTools();
        }

        function filterTools() {
            const query = document.getElementById('toolSearch').value.toLowerCase();
            const filtered = allTools.filter(t => {
                const matchesCat = selectedCategory === 'All' || t.category === selectedCategory;
                const matchesQuery = t.name.toLowerCase().includes(query) || t.description.toLowerCase().includes(query);
                return matchesCat && matchesQuery;
            });
            renderTools(filtered);
        }

        async function fetchNRI() {
            const res = await fetch('/api/nri');
            const data = await res.json();
            document.getElementById('statNri').innerText = data.directory.length;
            const grid = document.getElementById('nriGrid');
            grid.innerHTML = data.directory.map(item => `
                <div class="bg-slate-800/60 border border-slate-700/60 p-4 rounded-xl flex justify-between items-center">
                    <div>
                        <span class="text-[10px] font-semibold text-indigo-400 uppercase tracking-wider">${item.type}</span>
                        <h4 class="text-sm font-bold text-white mt-0.5">${item.name}</h4>
                        <p class="text-xs text-slate-400">${item.location}</p>
                    </div>
                    <a href="${item.link}" target="_blank" class="text-slate-400 hover:text-indigo-400"><i class="fa-solid fa-external-link"></i></a>
                </div>
            `).join('');
        }

        async function fetchNews() {
            const res = await fetch('/api/news');
            const data = await res.json();
            const grid = document.getElementById('newsGrid');
            grid.innerHTML = data.articles.map(a => `
                <a href="${a.link}" target="_blank" class="block bg-slate-800/40 border border-slate-700/60 p-4 rounded-xl">
                    <h4 class="text-sm font-semibold text-white">${a.title}</h4>
                    <p class="text-[11px] text-slate-500 mt-1">${a.source} • ${a.published}</p>
                </a>
            `).join('');
        }

        function openAdminModal() { document.getElementById('adminModal').classList.remove('hidden'); }
        function closeAdminModal() { document.getElementById('adminModal').classList.add('hidden'); }

        async function handleAddTool(e) {
            e.preventDefault();
            const payload = {
                name: document.getElementById('adminToolName').value,
                category: document.getElementById('adminCategory').value,
                description: document.getElementById('adminDesc').value,
                link: document.getElementById('adminLink').value,
                repo_link: document.getElementById('adminRepo').value,
                reference: document.getElementById('adminRef').value,
                icon: document.getElementById('adminIcon').value
            };

            const res = await fetch('/api/admin/add-tool', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-Email': currentUser.email
                },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                closeAdminModal();
                fetchTools();
                document.getElementById('addToolForm').reset();
            } else {
                alert('Admin verification failed. Please check your permissions.');
            }
        }
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
