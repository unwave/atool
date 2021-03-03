import re
import os
from collections import Counter

try:
    from . utils import locate_item
except:
    from utils import locate_item # for external testing

# import requests
# from bs4 import BeautifulSoup
# import tldextract
# import validators

def get_web_blendswap_info(url, content_path):

    url = url.split("?")[0].split("#")[0].rstrip("/")

    if not re.search(r"blendswap.com\/blend\/\d+$", url) and not re.search(r"blendswap.com\/blends\/view\/\d+$", url):
        return False, "Not valid BlendSwap url."

    id = url.split("/")[-1]
    preview_url = f"https://www.blendswap.com/blend_previews/{id}/0/0"

    import requests
    responce = requests.get(url)
    if responce.status_code != 200:
        return False, responce.text

    from bs4 import BeautifulSoup, NavigableString
    soup = BeautifulSoup(responce.text, "html.parser")

    name = soup.find("h1", {"class": "page-title"})
    if name.small:
        name.small.decompose()
    name = name.text.strip("\n ")

    sticky_list = soup.find("div", {"class": "card sticky-top card-sticky"})

    author = sticky_list.find("i", {"class": "far fa-user"}).parent

    author_id = re.search(r"(?<=\/)\d+$", author.a["href"])[0]
    author_url = f"https://www.blendswap.com/profile/{author_id}/blends"
    author = author.a.string

    licence = sticky_list.find("i", {"class": "fab fa-creative-commons"}).parent
    licence = re.findall(r"[\w\d-]+", licence.text)[1]

    licence_urls = {
        "CC-BY": "https://creativecommons.org/licenses/by/4.0/",
        "CC-BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
        "CC-BY-ND": "https://creativecommons.org/licenses/by-nd/4.0/",
        "CC-BY-NC": "https://creativecommons.org/licenses/by-nc/4.0/",
        "CC-BY-NC-SA": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "CC-BY-NC-ND": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "CC-0": "https://creativecommons.org/publicdomain/zero/1.0/",
        "GAL": "https://generalassetlicense.org/",
    }

    tags = soup.findAll("span", {"class": "badge badge-primary tag-badge"})
    tags = [tag.string for tag in tags]

    description = soup.find("div", {"class": "card-body blend-description"})

    description_list = []
    for tag in description.children:
        if isinstance(tag, NavigableString):
            continue
        if tag.name == "h3":
            continue 
        if tag.name == "p":
            for sub_tag in tag.children:
                if sub_tag.name == "a":
                    description_list.append(sub_tag.string + ": " + sub_tag["href"])
                else:
                    description_list.append(sub_tag.string)
            description_list.append("\n")
            
    description = ''.join(description_list)


    info = {
        "name": name,
        "url": url,
        "author": author,
        "author_url": author_url,
        "licence": licence,
        "licence_url": licence_urls.get(licence, ""),
        "tags": tags,
        "preview_url": preview_url,
        "description": description,
    }

    if content_path:
        responce = requests.get(preview_url)

        image_name = responce.url.split("?")[0].split("/")[-1]
        preview_temp_path = os.path.join(content_path, image_name)

        if responce.status_code == 200:
            with open(preview_temp_path, 'wb') as preview_file:
                preview_file.write(responce.content)
            info["preview_path"] = preview_temp_path

    return True, info

def get_web_sketchfab_info(url, content_path):

    url = url.split("?")[0].split("#")[0].rstrip("/")

    if not ("sketchfab.com/3d-models/" in url or "sketchfab.com/models/" in url):
        return False, "Not valid Sketchfab model url."

    id = re.search("(?<=-)\w+$", url)[0]

    #https://sketchfab.com/i/models/c2933b42e63f4f53bb061e323047615a

    import requests
    response = requests.get("https://sketchfab.com/i/models/"+ id)
    json = response.json()
    if response.status_code != 200:
        return False, json

    info = {
        "id": json["slug"],
        "name": json["name"],
        "url": json["viewerUrl"],
        "author": "",
        "author_url": json["user"]["profileUrl"],
        "licence": json["license"]["label"],
        "licence_url": "",
        "tags": json["tags"],
        "preview_url": "",
        "preview_path": "",
        "description": json["description"],
        # "dimensions": []
    }

    return True, info


def get_web_substance_source_info(url, content_path):

    url = url.split("?")[0].split("#")[0].rstrip("/")

    # get id form the url

    import requests
    responce = requests.get(url)
    if responce.status_code != 200:
        return False, responce.text

    data_dict = responce.json()

    preview_url = locate_item(data_dict, ("label", "main"), return_as = "parent")[0]["url"]

    asset = data_dict["data"]["assets"]["items"][0]

    extra_data = {dict["key"]: dict["value"] for dict in asset["extraData"]}

    dimensions = [float(dimension)/100.0 for dimension in extra_data["physicalSize"].split("/")]

    tags = asset["tags"]
    tags.append(extra_data["type"])

    info = {
        "id": extra_data["originalName"],
        "name": asset["title"],
        "url": "https://source.substance3d.com/allassets/" + asset["id"],
        "author": extra_data["author"],
        "author_url": "https://source.substance3d.com/",
        "licence": "EULA",
        "licence_url": "https://www.substance3d.com/legal/general-terms-conditions",
        "tags": tags,
        "preview_url": preview_url,
        "dimensions": dimensions
    }

    # info["preview_path"] = responce.content

def get_megascan_info_from_json(mega_info):

    name = None

    tags = mega_info.get("tags", [])
    tags.extend(mega_info.get("categories", []))

    semantic_tags = mega_info.get("semanticTags")
    if semantic_tags:
        semantic_tags.pop("industry", None)
        for key, value in semantic_tags.items():
            if isinstance(value, list):
                tags.extend(value)
            elif key in ("subject_matter", "asset_type"):
                tags.append(value)

        name = semantic_tags.get("name")

    if not name:
        name = mega_info.get("name", "")

    tags = list(map(lambda x: x.lower().strip(" "), dict.fromkeys(tags)))

    meta = {item["key"]: item["value"] for item in mega_info.get("meta", [])}

    number_pattern = re.compile("\d+(?:\.\d+)?")

    x = meta.get("length")
    if x:
        x = float(number_pattern.search(x).group(0))
    y = meta.get("width")
    if y:
        y = float(number_pattern.search(y).group(0))

    if not x and not y:
        scan_area = meta.get("scanArea")
        if not scan_area:
            sizes = locate_item(mega_info, "physicalSize", True, True)
            scan_area = Counter(sizes).most_common(1)[0][0]
        if scan_area:
            sizes = number_pattern.findall(scan_area)
            if len(sizes) == 2:
                x = float(sizes[0])
                y = float(sizes[1])
            elif len(sizes) == 1:
                x = y = float(sizes[0])
                
    if not x: x = 1
    if not y: y = 1
            
    z = meta.get("height")
    if z:
        z = float(number_pattern.search(z).group(0))
    else:
        z = 1

    dimensions = [x, y, z]

    # get original id slug
    # lb_id = re.search(fr".+_{megascan_id}", file.name)
    # if lb_id:
    #     lb_id = lb_id[0]
    # else:
    #     name = [file.name for file in files.get_files() if file.name.lower().endswith("_preview.png")]
    #     if name:
    #         match = re.search(fr".+(?=_{megascan_id})", name[0])
    #         if not match:
    #             match = re.search(fr".+(?=_{megascan_id})", file.name)
                
    #         if match:
    #             name = match[0].replace("_", " ")
    #         else:
    #             name = ""


    info = {
        # "id": "", # can get a slug from the json listing files
        "name": name,
        "url": f"https://quixel.com/megascans/home?assetId={mega_info['id']}",
        "author": "Quixel Megascans",
        "author_url": "https://quixel.com/megascans",
        "licence": "EULA",
        "licence_url": "https://quixel.com/terms",
        "tags": tags,
        # "preview_url": "", # probably the url is generated by some javascript
        # "description": "", # does not have it
        "dimensions": dimensions,
    }

    return info

def get_web_megascan_info(url, content_path):

    # https://quixel.com/megascans/home?assetId={megascan_id}
    match = re.search(r"(?<=assetId=)[a-zA-Z0-9]+", url)
    if not match:
        return False, "Not valid Megascan url."
    
    megascan_id = match[0]

    api_url = f"https://quixel.com/v1/assets/{megascan_id}"

    import requests
    responce = requests.get(api_url)
    if responce.status_code != 200:
        return False, responce.text

    mega_info = responce.json()

    info = get_megascan_info_from_json(mega_info)

    return True, info


'''
info = {
    "id": "",
    "name": "",
    "url": "",
    "author": "",
    "author_url": "",
    "licence": "",
    "licence_url": "",
    "tags": [],
    "preview_url": "",
    "description": "",
    "dimensions": [],
}
info["preview_path"] = ""
'''

SUPPORTED_SITES = {
    "sketchfab.com": get_web_sketchfab_info,
    "blendswap.com": get_web_blendswap_info,
    "source.substance3d.com": get_web_substance_source_info,
    "quixel.com": get_web_megascan_info
}

def get_web_info(url: str, content_path = None) -> tuple:
    """
    `Parameters`: \n
        `url`: url to the asset on the internet \n
    `Return`: tuple (is_success, result) \n
     - If `is_success` is `True` - `result` is a dictionary with the info. \n
     - If `is_success` is `False` - `result` is an error message. \n
    """

    import validators
    if not validators.url(url):
        return False, "Not valid URL."
    
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    if domain.startswith("www."):
        domain = domain[4:]
    
    print(domain)

    getter = SUPPORTED_SITES.get(domain)
    if not getter:
        print("Parser:", url, "The site is not supported.")
        return False, "The url is not supported."
    else:
        is_success, result = getter(url, content_path)
        print("Parser:", url, result)
        return is_success, result
