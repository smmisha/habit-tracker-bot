import re

def analyze():
    with open("scratch/june10.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    dates = re.findall(r'<div[^>]*class="tabContent"[^>]*data-date="([^"]+)"', html)
    print("Dates in tabContent containers:")
    for d in dates:
        print(f"- {d}")
        
    # Find all h2 elements and their surrounding context
    matches = list(re.finditer(r'<div[^>]*class="tabContent"[^>]*data-date="([^"]+)"', html))
    for i in range(len(matches)):
        start_idx = matches[i].start()
        end_idx = matches[i+1].start() if i+1 < len(matches) else len(html)
        day_html = html[start_idx:end_idx]
        
        h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', day_html, re.DOTALL)
        h2_text = re.sub(r'<[^>]+>', '', h2_match.group(1)).strip() if h2_match else "No H2"
        
        scrp_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', day_html, re.DOTALL)
        scrp_text = re.sub(r'<[^>]+>', '', scrp_match.group(1)).strip() if scrp_match else "No Scripture"
        scrp_text = " ".join(scrp_text.split())
        
        print(f"\nBlock date: {dates[i]}")
        print(f"H2: {h2_text}")
        print(f"Scripture: {scrp_text}")

if __name__ == "__main__":
    analyze()
