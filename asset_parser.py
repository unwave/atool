import re
import os
import json
import subprocess
import tempfile
from collections import Counter

import logging
log = logging.getLogger("atool")

try:
    from . utils import locate_item, deduplicate, remove_empty, extract_zip
    from . type_definer import get_type
except:
    from utils import locate_item, deduplicate, remove_empty, extract_zip # for external testing
    from type_definer import get_type

try:
    import bpy
except:
    pass

# import requests
# from bs4 import BeautifulSoup
# import tldextract
# import validators

try:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip") as key:
        seven_z = winreg.QueryValueEx(key, "Path")[0]
        seven_z = os.path.join(seven_z, "7z.exe")
except:
    seven_z = "7z"
finally:
    try:
        subprocess.run([seven_z], stdout=subprocess.DEVNULL)
    except:
        print("7z is not found. The sbsar info auto import is unavailable.")
        seven_z = None


def get_web_file(url, content_folder = None, content_path = None, headers = None):
    assert not(content_folder == None and content_path == None)
    
    import requests
    if headers:
        response = requests.get(url, headers=headers)
    else:
        response = requests.get(url)
    if response.status_code != 200:
        return False, response.text

    if content_path:
        os_path = content_path
        os.makedirs(os.path.dirname(os_path), exist_ok=True)
    else:
        file_name = response.url.split("?")[0].split("#")[0].split("/")[-1] # todo: check if does not have extension
        os_path = os.path.join(content_folder, file_name)
        os.makedirs(content_folder, exist_ok=True)

    assert not os.path.exists(os_path)
    with open(os_path, 'wb') as file:
        file.write(response.content)
    return True, os_path


def get_web_cc0textures_info(url, content_folder):

    if "cc0textures.com" in url: # https://cc0textures.com/view?id=Plaster003
        match = re.search(r"(?<=id=)[a-zA-Z0-9]+", url)
        if not match:
            return False, "Not valid CC0textures url."
        id = match.group(0)
    elif "cc0.link" in url: # https://cc0.link/a/Plaster003
        url = url.split("?")[0].split("#")[0].rstrip("/")
        id = url.split("/")[-1]

    api_url = f"https://cc0textures.com/api/v2/full_json?id={id}&sort=Latest&limit=1&include=tagData%2CdisplayData%2CdimensionsData%2CdownloadData%2CpreviewData%2CimageData"

    headers = {'User-Agent': 'Blender'}

    import requests
    response = requests.get(api_url, headers=headers)
    if response.status_code != 200:
        return False, response.text
        
    json = response.json()
    if response.status_code != 200:
        return False, json

    asset = json["foundAssets"][0]

    info = {
    "id": id,
    "name": asset["displayName"],
    "url": f"https://cc0textures.com/view?id={id}",
    "author": "cc0textures",
    "author_url": "https://cc0textures.com",
    "licence": "CC0",
    "licence_url": "https://docs.cc0textures.com/licensing.html",
    "tags": asset["tags"],
    "preview_url": asset["previewImage"]["1024-PNG"],
    }

    dimensionX = asset.get("dimensionX")
    if not dimensionX:
        dimensionX = 1
    dimensionY = asset.get("dimensionY")
    if not dimensionY:
        dimensionY = 1
    dimensionZ = asset.get("dimensionZ")
    if not dimensionZ:
        dimensionZ = 0.1

    info["dimension"] = [dimensionX, dimensionY, dimensionZ]

    
    description = asset.get("description")
    if description:
        info["dimensions"] = description


    if content_folder:
        download = locate_item(asset["downloadFolders"], ("attribute", "4K-JPG"), return_as = "parent")[0]
        url = download["downloadLink"] # "https://cc0textures.com/get?file=Plaster003_4K-PNG.zip"
        info["downloadLink"] = url
        info["fileName"] = download["fileName"] # "Plaster003_4K-PNG.zip"

    return True, info

def get_web_cc0textures_asset(url, content_folder):

    is_ok, result = get_web_cc0textures_info(url, content_folder)
    if not is_ok:
        return False, result

    info = result

    url = info.pop("downloadLink")
    content_path = os.path.join(content_folder, info.pop("fileName"))

    headers = {'User-Agent': 'Blender'}

    is_ok, result = get_web_file(url, content_path = content_path, headers=headers)
    if is_ok:
        extract_zip(result, path = content_folder)
        os.remove(result)
    else:
        print(f"Cannot download asset {url}", result)

    url = info["preview_url"]
    is_ok, result = get_web_file(url, content_folder, headers=headers)
    if is_ok:
        info["preview_path"] = result
    else:
        print(f"Cannot download preview {url}", result)

    return True, info



def get_web_3dmodelhaven_asset(url, content_folder):

    # https://3dmodelhaven.com/model/?m=sofa_02

    if not re.search(r"3dmodelhaven.com\/model\/", url):
        return False, "Not valid 3d Model Haven url."

    import requests
    response = requests.get(url)
    if response.status_code != 200:
        return False, response.text

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.text, 'html.parser')

    meta = soup.findAll(name="meta")
    for item in meta:
        key = item.attrs.get("name")
        if key == "tex1:tags": # <meta name="tex1:tags" content="outdoor industrial,barrel,water,plastic" />
            tags = re.split(",| ", item["content"])
        elif key == "tex1:name": # <meta name="tex1:name" content="Barrel 02" />
            name = item["content"]
        elif key == "author": # <meta name="author" content="Jorge Camacho">
            author = item["content"]
        elif key == "tex1:preview-image": # <meta name="tex1:preview-image" content="https://3dmodelhaven.com/files/mod_images/renders/Barrel_02.jpg" />
            preview_url = item["content"]
        elif key == "author": # <meta name="author" content="Jorge Camacho">
            author = item["content"]

    id = re.search(r"(?<=m=)[^&#]+", url).group(0)

    info = {
        "id": id,
        "name": name,
        "url": url,
        "author": author,
        "author_url": fr"https://3dmodelhaven.com/models/?a={author}",
        "licence": "CC-0",
        "licence_url": r"https://3dmodelhaven.com/p/license.php",
        "tags": tags,
        "preview_url": preview_url,
        # "description": "",
        # "dimensions": [],
    }

    files = soup.find_all(name="a", href=re.compile("\/files\/"))
    base_url = r"https://3dmodelhaven.com"


    models = []
    for file in files:
        href = file["href"]
        if href.endswith(".blend"):
            models.append(href)

    for model in models:
        url = base_url + model
        is_ok, result = get_web_file(url, content_folder)
        if not is_ok:
            print(f"Cannot download {url}", result)
            return False, result
        else:
            blend = result
    
    script = "import bpy, json\n" \
    "print(json.dumps([bpy.path.abspath(image.filepath) for image in bpy.data.images if image.source == 'FILE']))"

    result = subprocess.run([bpy.app.binary_path, blend, "--factory-startup", "-b", "--python-expr", script], stdout=subprocess.PIPE, text=True)
    paths = json.loads(result.stdout.split("\n")[0])
    names = tuple([os.path.basename(path) for path in paths])

    textures = []
    for file in files:
        href = file["href"]
        if href.endswith(names):
            textures.append(href)

    base = os.path.dirname(os.path.commonpath(textures))
    for texture in textures:
        url = base_url + texture
        content_path = os.path.join(content_folder, os.path.relpath(texture, start=base))
        is_ok, result = get_web_file(url, content_path=content_path)
        if not is_ok:
            print(f"Cannot download {url}", result)

    is_ok, result = get_web_file(preview_url, content_folder)
    if not is_ok:
        print(f"Cannot download {preview_url}", result)
    else:
        info["preview_path"] = result
    
    return True, info



def get_web_texturehaven_info(url, content_folder):
    # https://texturehaven.com/tex/?t=brick_wall_003
    url = url.split("#")[0]

    if not "texturehaven.com/tex/" in url:
        return False, "Not valid Texture Haven url."
        
    match = re.search(r"(?<=t=)[a-zA-Z0-9_]+", url)
    id = match.group(0)

    import requests
    response = requests.get(url)
    if response.status_code != 200:
        return False, response.text

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.text, 'html.parser')

    dimensions = []
    tags = []

    for item in soup.find(name="div", id = "item-info").findAll("li"):
        title = item.get("title")
        if not title:
            b = item.find('b')
            if b:
                title = b.string
        if title:
            if title.startswith("Author"):
                author = title.split(":")[1].strip()
                author_url = f"https://texturehaven.com/textures/?a={author}"
            elif title.startswith("Real-world"):
                dimensions = title.split(":")[1].strip()
                number_pattern = re.compile("\d+\.?\d*")
                dimensions = [float(number) for number in number_pattern.findall(dimensions)]
            elif title.startswith(("Categories", "Tags")):
                tags.extend([a.string.lower().strip() for a in item.findAll("a")])

    preview_url = "https://texturehaven.com" + soup.find(name = "div", id = "item-preview").find("img")["src"]

    if len(dimensions) == 2:
        dimensions.append(0.1)

    info = {
        "id": id,
        "name": id,
        "url": url,
        "author": author,
        "author_url": author_url,
        "licence": "CC0",
        "licence_url": "https://texturehaven.com/p/license.php",
        "tags": tags,
        "preview_url": preview_url,
        # "description": "",
        "dimensions": dimensions,
    }

    if content_folder:
        downloads = []

        # for a in soup.findAll("a"):
        #     if a.get("download"):
        #         href = a["href"]
        #         if "/png/4k/" in href:
        #             name = href.split("/")[-1].lower()
        #             type = get_type(name)
        #             if type and len(type) == 1 and type[0] in ('diffuse', 'albedo', 'displacement', 'normal', 'roughness', 'ambient_occlusion'):
        #                 downloads.append("https://texturehaven.com" + href)

        for a in soup.findAll("a"):
            if a.get("download"):
                href = a["href"]
                if "/4k/" in href:
                    name = href.split("/")[-1].lower()
                    type = get_type(name, config={"is_rgb_plus_alpha": True})
                    if not type or len(type) != 1:
                        continue
                    type = type[0]
                    if ("/jpg/4k/" in href and type in ('diffuse', 'albedo', 'normal', 'roughness', 'ambient_occlusion')) or ("/png/4k/" in href and type in ('displacement',)):
                        downloads.append("https://texturehaven.com" + href)

        for download in downloads.copy():
            if "dx_normal" in download.lower():
                for _download in downloads.copy():
                    if "gl_normal" in _download.lower():
                        downloads.remove(download)

        downloads = deduplicate(downloads)
        info["downloads"] = downloads

    return True, info


def get_web_texturehaven_asset(url, content_folder):

    is_ok, result = get_web_texturehaven_info(url, content_folder)
    if not is_ok:
        return False, result

    info = result

    downloads = info.pop("downloads")
    for download in downloads:
        is_ok, result = get_web_file(download, content_folder)
        if not is_ok:
            print(f"Cannot download {download}", result)

    preview_url = info["preview_url"]
    is_ok, result = get_web_file(preview_url, content_folder)
    if not is_ok:
        print(f"Cannot download {preview_url}", result)
    else:
        info["preview_path"] = result

    return True, info


def get_info_from_substance_json(data):

    preview_url = locate_item(data, ("label", "main"), return_as = "parent")[0]["url"]

    extra_data = {dict["key"]: dict["value"] for dict in data["extraData"]}

    dimensions = []
    physicalSize = extra_data.get("physicalSize")
    if physicalSize:
        dimensions = [float(dimension)/100.0 for dimension in physicalSize.split("/")]

    tags = data["tags"]
    tags.append(extra_data["type"])

    info = {
        # "id": extra_data["originalName"], # not always
        "name": data["title"],
        "url": "https://source.substance3d.com/allassets/" + data["id"],
        "author": extra_data["author"],
        "author_url": "https://source.substance3d.com/",
        "licence": "EULA",
        "licence_url": "https://www.substance3d.com/legal/general-terms-conditions",
        "tags": tags,
        "preview_url": preview_url,
        # "description": "",
        "dimensions": dimensions
    }

    # info["preview_path"] = ""

    remove_empty(info)
    return info

def get_info_from_sbsar_xml(xml_file):
    with open(xml_file , 'r',encoding = "utf-8") as xml_text:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(xml_text.read(), "html.parser")
        graph = soup.find("graph")
        attrs = graph.attrs

        tags = []
        keywords = attrs.get("keywords")
        if keywords:
            tags = re.split(r" |;|,", keywords.strip("; ").lower())
        
        category = attrs.get("category")
        if category:
            tags.extend(re.split(r" |/|,", category.lower()))
        
        tags = deduplicate(tags)
        tags = list(filter(None, tags))

        id = None
        pkgurl = attrs.get("pkgurl")
        if pkgurl:
            match = re.search(r"(?<=pkg:\/\/).+", pkgurl)
            if match:
                id = match.group(0)

        if id:
            name = id
        else:
            name = os.path.splitext(os.path.basename(xml_file))[0]
        label = attrs.get("label")
        if label:
            name = label.strip(" ")

        dimensions = []
        physicalsize = attrs.get("physicalsize")
        if physicalsize:
            dimensions = [float(dimension)/100.0 for dimension in physicalsize.split(",")]

        sbsar_info = {
            "id": id,
            "name": name,
            # "url": "",
            "author":  attrs.get("author", ""),
            "author_url": attrs.get("authorurl", ""),
            # "licence": "",
            # "licence_url": "",
            "tags": tags,
            # "preview_url": "",
            "description": attrs.get("description", ""),
            "dimensions": dimensions,
            "xml_attrs": attrs
        }

        remove_empty(sbsar_info)
        return sbsar_info

def get_info_from_sbsar(sbsar):

    global seven_z
    if not seven_z:
        return False, "7z is not found."
    
    with tempfile.TemporaryDirectory() as temp_dir:
        subprocess.run([seven_z, "e", sbsar, "-o" + temp_dir, "*.xml" ,"-r"], stdout=subprocess.PIPE, check=True)
        xml_file = list(os.scandir(temp_dir))[0].path
        return True, get_info_from_sbsar_xml(xml_file)

def get_web_substance_source_info_by_label(label):

    substance_api_url = "https://source-api.substance3d.com/beta/graphql"

    query_assets =\
        'query Assets($page: Int, $limit: Int = 1, $search: String, $filters: AssetFilters, $sortDir: SortDir = desc, $sort: AssetSort = byPublicationDate) {\n'\
        '  assets(search: $search, filters: $filters, sort: $sort, sortDir: $sortDir, page: $page, limit: $limit) {\n'\
        '    total\n'\
        '    hasMore\n'\
        '    items {\n'\
        '      id\n'\
        '      title\n'\
        '      tags\n'\
        '      cost\n'\
        '      new\n'\
        '      free\n'\
        '      downloadsRecentlyUpdated\n'\
        '      attachments {\n'\
        '        id\n'\
        '        tags\n'\
        '        label\n'\
        '        ... on PreviewAttachment {\n'\
        '          kind\n'\
        '          url\n'\
        '          __typename\n'\
        '        }\n'\
        '        ... on DownloadAttachment {\n'\
        '          url\n'\
        '          __typename\n'\
        '        }\n'\
        '        __typename\n'\
        '      }\n'\
        '      extraData {\n'\
        '        key\n'\
        '        value\n'\
        '        __typename\n'\
        '      }\n'\
        '      type\n'\
        '      status\n'\
        '      __typename\n'\
        '    }\n'\
        '    __typename\n'\
        '  }\n'\
        '}\n'

    substance_search_payload = {
        "operationName": "Assets",
        "variables": {
            "limit": 1,
            "sortDir": "desc",
            "sort": "bySearchScore",
            "search": "\"" + label + "\"",
            "filters": {"status": ["published"]},
        },
        "query": query_assets
    }

    import requests
    response = requests.post(substance_api_url, json = substance_search_payload)
    if response.status_code != 200:
        return False, response.text

    search_json = response.json()
    items = search_json["data"]["assets"]["items"]
    if not items:
        return None

    info = get_info_from_substance_json(items[0])

    if info["name"] == label: # name == title form substance source json
        return info
    else:
        print(info["title"], "!=" ,label)
        return None

def get_web_substance_source_info(url, content_folder):

    # https://source.substance3d.com/allassets/3a92437f756236ad41ca5603286e0068768f1635?free=true

    id = url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]

    substance_api_url = "https://source-api.substance3d.com/beta/graphql"

    query_asset = 'query Asset($id: String!) {\n'\
        '  asset(id: $id) {\n'\
        '    id\n'\
        '    title\n'\
        '    tags\n'\
        '    cost\n'\
        '    new\n'\
        '    free\n'\
        '    downloadsRecentlyUpdated\n'\
        '    attachments {\n'\
        '      id\n'\
        '      tags\n'\
        '      label\n'\
        '      ... on PreviewAttachment {\n'\
        '        url\n'\
        '        kind\n'\
        '        __typename\n'\
        '      }\n'\
        '      ... on DownloadAttachment {\n'\
        '        url\n'\
        '        __typename\n'\
        '      }\n'\
        '      __typename\n'\
        '    }\n'\
        '    extraData {\n'\
        '      key\n'\
        '      value\n'\
        '      __typename\n'\
        '    }\n'\
        '    type\n'\
        '    createdAt\n'\
        '    status\n'\
        '    __typename\n'\
        '  }\n'\
        '}'

    substance_info_payload = {
        "operationName": "Asset",
        "variables": {
            "id": id
            },
        "query": query_asset
        }

    import requests
    response = requests.post(substance_api_url, json = substance_info_payload)
    if response.status_code != 200:
        return False, response.text

    try:
        response_json = response.json()
        data_dict = response_json["data"]["asset"]
        info = get_info_from_substance_json(data_dict)
        return True, info
    except:
        return False, response.text


def get_web_blendswap_info(url, content_folder):

    url = url.split("?")[0].split("#")[0].rstrip("/")

    if not re.search(r"blendswap.com\/blend\/\d+$", url) and not re.search(r"blendswap.com\/blends\/view\/\d+$", url):
        return False, "Not valid BlendSwap url."

    import requests
    response = requests.get(url)
    if response.status_code != 200:
        return False, response.text

    url = response.url # can change
    id = url.split("/")[-1]
    preview_url = f"https://www.blendswap.com/blend_previews/{id}/0/0"

    from bs4 import BeautifulSoup, NavigableString
    soup = BeautifulSoup(response.text, "html.parser")

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

    if content_folder:
        is_ok, result = get_web_file(preview_url, content_folder)
        if is_ok:
            info["preview_path"] = result
        else:
            print("Cannot get preview from:", preview_url)
            print(result)

    return True, info


def get_web_sketchfab_info(url, content_folder):

    url = url.split("?")[0].split("#")[0].rstrip("/")

    if not ("sketchfab.com/3d-models/" in url or "sketchfab.com/models/" in url):
        return False, "Not valid Sketchfab model url."

    id = url.split("/")[-1].split("-")[-1]

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
        "author": json["user"]["displayName"], 
        "author_url": json["user"]["profileUrl"],
        "licence": json["license"]["label"],
        "licence_url": json["license"]["url"],
        "tags": json["tags"],
        "preview_url": "",
        "preview_path": "",
        "description": json["description"],
        # "dimensions": []
    }

    return True, info


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

def get_web_megascan_info(url, content_folder):

    # https://quixel.com/megascans/home?assetId={megascan_id}
    match = re.search(r"(?<=assetId=)[a-zA-Z0-9]+", url)
    if not match:
        return False, "Not valid Megascan url."
    
    megascan_id = match[0]

    api_url = f"https://quixel.com/v1/assets/{megascan_id}"

    import requests
    response = requests.get(api_url)
    if response.status_code != 200:
        return False, response.text

    mega_info = response.json()

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

INFO_SUPPORTED_SITES = {
    "sketchfab.com": get_web_sketchfab_info,
    "blendswap.com": get_web_blendswap_info,
    "source.substance3d.com": get_web_substance_source_info,
    "quixel.com": get_web_megascan_info,
    "cc0textures.com": get_web_cc0textures_info,
    "cc0.link": get_web_cc0textures_info,
    "texturehaven.com": get_web_texturehaven_info
}

ASSET_SUPPORTED_SITES = {
    "3dmodelhaven.com": get_web_3dmodelhaven_asset,
    "texturehaven.com": get_web_texturehaven_asset,
    "cc0textures.com": get_web_cc0textures_asset,
    "cc0.link": get_web_cc0textures_asset
}

def get_web(url: str, content_folder = None, as_asset = False) -> tuple:
    """
    `Parameters`: \n
        `url`: url to the asset on the internet \n
        `content_folder`: a folder to store downloads \n
        `as_asset`: if the url is a supported autogetter asset url
    `Return`: tuple (is_ok, result) \n
     - If `is_ok` is `True` - `result` is a dictionary with the info. \n
     - If `is_ok` is `False` - `result` is an error message. \n
    """

    if as_asset and not content_folder:
        raise Exception("If `as_asset` is True `content_folder` must be supplied.")

    # if not re.search(r"^((https?|ftp|smtp):\/\/)?(www.)?[a-z0-9]+\.[a-z]+(\/[a-zA-Z0-9#]+\/?)*$", url):
    #     return False, "Not valid URL: " + url

    import validators

    if not validators.url(url):
        url = "https://" + url
        if not validators.url(url):
            return False, "Not valid URL: " + url
    
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    if domain.startswith("www."):
        domain = domain[4:]

    if as_asset:
        getter = ASSET_SUPPORTED_SITES.get(domain)
    else:
        getter = INFO_SUPPORTED_SITES.get(domain)
    if not getter:
        print("Parser:", url, "The site is not supported.")
        return False, "The url is not supported."
    else:
        is_ok, result = getter(url, content_folder)
        print("Parser:", url, result)
        return is_ok, result
