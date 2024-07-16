from flask import Flask, request, render_template, jsonify
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import re
import json
import concurrent.futures
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

class WebScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def get_sitemap_url(self, domain):
        common_locations = [
            f"https://{domain}/sitemap.xml",
            f"https://{domain}/sitemap_index.xml",
            f"https://{domain}/sitemap-index.xml",
        ]
        for url in common_locations:
            response = self.session.get(url, allow_redirects=True)
            if response.status_code == 200 and 'xml' in response.headers.get('Content-Type', ''):
                return url
        
        robots_url = f"https://{domain}/robots.txt"
        response = self.session.get(robots_url)
        if response.status_code == 200:
            sitemap_line = re.search(r"Sitemap: (.+)", response.text)
            if sitemap_line:
                return sitemap_line.group(1)
        
        return None

    def parse_sitemap(self, sitemap_url):
        response = self.session.get(sitemap_url)
        root = ET.fromstring(response.content)
        
        urls = []
        for elem in root.iter():
            if 'loc' in elem.tag:
                urls.append(elem.text)
            elif 'sitemap' in elem.tag:
                urls.extend(self.parse_sitemap(elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text))
        
        return urls

    def is_ecommerce(self, soup):
        ecommerce_indicators = [
            "add to cart",
            "buy now",
            "product",
            "price",
            "shipping",
            "checkout"
        ]
        page_text = soup.get_text().lower()
        return any(indicator in page_text for indicator in ecommerce_indicators)

    def scrape_ecommerce(self, url):
        response = self.session.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        product = {
            "url": url,
            "name": soup.find("h1").text.strip() if soup.find("h1") else "",
            "price": soup.find("meta", {"property": "product:price:amount"})["content"] if soup.find("meta", {"property": "product:price:amount"}) else "",
            "description": soup.find("meta", {"name": "description"})["content"] if soup.find("meta", {"name": "description"}) else "",
            "images": [urljoin(url, img["src"]) for img in soup.find_all("img") if "product" in img.get("class", [])],
        }
        
        return product

    def scrape_non_ecommerce(self, url):
        response = self.session.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        content = {
            "url": url,
            "title": soup.find("title").text.strip() if soup.find("title") else "",
            "description": soup.find("meta", {"name": "description"})["content"] if soup.find("meta", {"name": "description"}) else "",
            "main_content": soup.find("main").get_text(strip=True) if soup.find("main") else soup.get_text(strip=True),
        }
        
        return content

    def scrape_blog(self, url):
        response = self.session.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        blog_post = {
            "url": url,
            "title": soup.find("h1").text.strip() if soup.find("h1") else "",
            "date": soup.find("time")["datetime"] if soup.find("time") else "",
            "content": soup.find("article").get_text(strip=True) if soup.find("article") else "",
        }
        
        return blog_post

    def scrape_url(self, url, is_ecommerce):
        if "/blog/" in url:
            return self.scrape_blog(url)
        elif is_ecommerce:
            return self.scrape_ecommerce(url)
        else:
            return self.scrape_non_ecommerce(url)

    def run(self, domain):
        sitemap_url = self.get_sitemap_url(domain)
        if not sitemap_url:
            return {"error": "Sitemap not found. Exiting."}
        
        urls = self.parse_sitemap(sitemap_url)
        
        sample_url = urls[0]
        response = self.session.get(sample_url)
        soup = BeautifulSoup(response.content, 'html.parser')
        is_ecommerce_site = self.is_ecommerce(soup)
        
        blog_urls = [url for url in urls if "/blog/" in url]
        non_blog_urls = [url for url in urls if "/blog/" not in url]
        
        urls_to_scrape = non_blog_urls + blog_urls
        
        scraped_data = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(self.scrape_url, url, is_ecommerce_site): url for url in urls_to_scrape}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    data = future.result()
                    scraped_data.append(data)
                except Exception as exc:
                    scraped_data.append({"url": url, "error": str(exc)})
        
        return scraped_data

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form['url']
        domain = urlparse(url).netloc
        scraper = WebScraper()
        result = scraper.run(domain)
        return jsonify(result)
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
