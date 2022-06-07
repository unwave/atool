import re
import os
import json
import subprocess
import tempfile
import operator
import typing
from collections import Counter

import logging
log = logging.getLogger("atool")


if __package__:
    import bpy
    from . import utils
    from . import bl_utils
    # from . import type_definer
else:
    import utils
    # import bl_utils
    # import type_definer
    
    # class bl_utils:

    #     def iter_with_progress(iterator, *args, **kw):
    #         for i in iterator:
    #             yield i

    #     def download_with_progress(response, path, *args, **kw):
    #         with open(path, "wb") as f:
    #             for chunk in response.iter_content(chunk_size=4096):
    #                 f.write(chunk)
    
    # bl_utils = bl_utils()


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

def get_base_url(url):
    return url.split("?")[0].split("#")[0].rstrip("/")

def get_web_file(url, content_folder = None, content_path = None, headers = None):
    assert not(content_folder == None and content_path == None)
    
    import requests
    response = requests.get(url, headers=headers, stream=True)
    if response.status_code != 200:
        return False, response.text

    if content_path:
        os_path = content_path
        file_name = os.path.basename(os_path)
        os.makedirs(os.path.dirname(os_path), exist_ok=True)
    else:
        file_name = response.url.split("?")[0].split("#")[0].split("/")[-1] # todo: check if does not have extension
        os_path = os.path.join(content_folder, file_name)
        os.makedirs(content_folder, exist_ok=True)

    assert not os.path.exists(os_path)

    total = int(response.headers.get('content-length'))
    bl_utils.download_with_progress(response, os_path, total= total, indent=1, prefix = file_name)

    return True, os_path


def get_web_ambientcg_info(url, content_folder):

    # https://cc0textures.com/view?id=Plaster003
    # https://ambientcg.com/view?id=Bricks056

    if "cc0textures.com" in url or "ambientcg.com" in url: 
        match = re.search(r"(?<=id=)[a-zA-Z0-9]+", url)
        if not match:
            return False, "Not valid Ambient CG url."
        id = match.group(0)
    elif "cc0.link" in url: # https://cc0.link/a/Plaster003
        url = url.split("?")[0].split("#")[0].rstrip("/")
        id = url.split("/")[-1]

    api_url = f"https://ambientcg.com/api/v2/full_json?id={id}&sort=Latest&limit=1&include=tagData%2CdisplayData%2CdimensionsData%2CdownloadData%2CpreviewData%2CimageData"

    headers = {'User-Agent': 'Blender'}

    import requests
    response = requests.get(api_url, headers=headers)
    if response.status_code != 200:
        return False, response.text
        
    json = response.json()

    asset = json["foundAssets"][0]

    if asset["dataType"] == "3DModel":
        return False, "3DModel is not supported yet."

    dimensions = {}
    for letter, name in zip('xyz', ("dimensionX", "dimensionY", "dimensionZ")):
        dimension = asset.get(name)
        if dimension:
            dimensions[letter] = int(dimension)/100
            
    info = {
    "id": id,
    "name": asset["displayName"],
    "url": f"https://ambientcg.com/view?id={id}",
    "author": "ambientcg",
    "author_url": "https://ambientcg.com",
    "licence": "CC0",
    "licence_url": "https://help.ambientcg.com/01-General/Licensing.html",
    "tags": asset["tags"],
    "preview_url": asset["previewImage"]["1024-PNG"],
    "description": asset.get("description"),
    "dimensions": dimensions
    }
    
    info['material_settings'] = {'Y- Normal Map': 1}

    if content_folder:
        download = utils.locate_item(asset["downloadFolders"], ("attribute", "4K-JPG"), return_as = "parent")[0]
        url = download["downloadLink"] # "https://cc0textures.com/get?file=Plaster003_4K-PNG.zip"
        info["downloadLink"] = url
        info["fileName"] = download["fileName"] # "Plaster003_4K-PNG.zip"

    utils.remove_empty(info)
    return True, info

def get_web_ambientcg_asset(url, content_folder):

    is_ok, result = get_web_ambientcg_info(url, content_folder)
    if not is_ok:
        return False, result

    info = result

    url = info.pop("downloadLink")
    content_path = os.path.join(content_folder, info.pop("fileName"))

    headers = {'User-Agent': 'Blender'}

    is_ok, result = get_web_file(url, content_path = content_path, headers=headers)
    if is_ok:
        utils.extract_zip(result, path = content_folder)
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


def get_web_polyhaven_info(url, content_folder):
    # https://polyhaven.com/a/aerial_rocks_02
    url = get_base_url(url)

    if not "polyhaven.com/a/" in url:
        return False, "Not valid Poly Haven url."
        
    # aerial_rocks_02
    id = url.split('/')[-1]

    api_url = f"https://api.polyhaven.com/info/{id}"

    import requests
    response = requests.get(api_url)
    if response.status_code != 200:
        return False, response.text

    data = response.json() # type: dict

    type_to_text = {
        0: 'hdri',
        1: 'material',
        2: 'model',
    }
    type = type_to_text[data['type']]
    
    if type == 'hdri':
        raise NotImplementedError('HDRIs are not supported yet.')

    authors = data.get('authors', {})
    authors_list = list(authors)
    authors = ', '.join(authors_list)
    author_url = f"https://polyhaven.com/textures?a={authors_list[0]}" 

    if type == 'material':
        preview_url = f"https://cdn.polyhaven.com/asset_img/thumbs/{id}.png?height=780"
    elif type == 'model':
        preview_url = f"https://cdn.polyhaven.com/asset_img/primary/{id}.png?height=780"

    tags = data.get('tags', [])
    tags.extend(data.get('categories', []))

    dimensions = {}
    if type == 'material':
        dimensions_text = data.get('scale')
        if dimensions_text:
            number_pattern = re.compile("\d+\.?\d*")
            for letter, number in zip('xyz', number_pattern.findall(dimensions_text)):
                dimensions[letter] = float(number)

    info = {
        "id": id,
        "name": data.get('name', id),
        "url": url,
        "author": authors,
        "author_url": author_url,
        "licence": "CC0",
        "licence_url": "https://polyhaven.com/license",
        "tags": tags,
        "preview_url": preview_url,
        # "description": "",
        "dimensions": dimensions,
    }

    utils.remove_empty(info)
    
    api_url = f"https://api.polyhaven.com/files/{id}"
    response = requests.get(api_url)
    if response.status_code == 200:
        
        data = response.json() 
        blend = data['blend']['4k']['blend']
        include = blend['include'] # type: dict
        
        if type == 'material':
            with tempfile.TemporaryDirectory() as temp_dir:
                is_ok, result = get_web_file(blend['url'], temp_dir)
                if is_ok:
                    process = bl_utils.run_blender(result, script=utils.get_script('get_polyhaven_dimensions.py'), stdout=subprocess.PIPE)
                    info['dimensions'] = json.loads(process.stdout.split("\n")[0])
                else:
                    print(f"Cannot get the blend file: {blend['url']}")
                    print(response.text)
    else:
        if content_folder:
            return False, response.text
        else:
            print(f"Cannot get the files info: {api_url}")
            print(response.text)

    if content_folder:
        downloads = []

        if type == 'material':
            for rel_path, texture in include.items():
                downloads.append({'url': texture['url']})
                
        elif type == 'model':
            downloads.append({'url': blend['url']})
            for rel_path, texture in include.items():
                downloads.append({
                    'rel_path': rel_path,
                    'url': texture['url']
                })

        info["downloads"] = downloads
        
    return True, info

def get_web_polyhaven_asset(url, content_folder):

    is_ok, info = get_web_polyhaven_info(url, content_folder)
    if not is_ok:
        return False, info

    downloads = info.pop('downloads') # type: typing.List[dict]
    for download in bl_utils.iter_with_progress(downloads, prefix = "Files"):
        rel_path = download.get('rel_path')
        if rel_path:
            content_path = os.path.join(content_folder, *os.path.split(rel_path))
            is_ok, result = get_web_file(download['url'], content_path = content_path)
        else:
            is_ok, result = get_web_file(download['url'], content_folder)
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

    preview_url = utils.locate_item(data, ("label", "main"), return_as = "parent")[0]["url"]

    extra_data = {dict["key"]: dict["value"] for dict in data["extraData"]}

    dimensions = {}
    physicalSize = extra_data.get("physicalSize")
    if physicalSize:
        for letter, dimension in zip('xyz' , physicalSize.split("/")):
            dimensions[letter] = float(dimension)/100.0

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

    utils.remove_empty(info)
    return info

def get_info_from_sbsar_xml(xml_file):
    with open(xml_file , 'r',encoding = "utf-8") as xml_text:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(xml_text.read(), "html.parser")
        graph = soup.find("graph")
        attrs = graph.attrs # type: dict

        tags = []
        keywords = attrs.get("keywords")
        if keywords:
            tags = re.split(r" |;|,", keywords.strip("; ").lower())
        
        category = attrs.get("category")
        if category:
            tags.extend(re.split(r" |/|,", category.lower()))
        
        tags = utils.deduplicate(tags)
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

        dimensions = {}
        physicalsize = attrs.get("physicalsize")
        if physicalsize:
            for letter, dimension in zip('xyz' , physicalsize.split(",")):
                dimensions[letter] = float(dimension)/100.0

        info = {
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


        utils.remove_empty(info)
        return info

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
            #"filters": {"status": ["published"]},
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

    if label in info["name"]: # name == title form substance source json
        return info
    else:
        print(items[0]["title"], "!=" ,label)
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
    if response.status_code != 200:
        return False, response.text

    json = response.json()

    preview_url = max(json["thumbnails"]["images"], key=operator.itemgetter("size"))["url"]

    info = {
        "id": json["slug"],
        "name": json["name"],
        "url": json["viewerUrl"],
        "author": json["user"]["displayName"], 
        "author_url": json["user"]["profileUrl"],
        "licence": json["license"]["label"],
        "licence_url": json["license"]["url"],
        "tags": json["tags"],
        "preview_url": preview_url,
        "description": json["description"],
        # "dimensions": []
    }

    if content_folder:
        is_ok, result = get_web_file(preview_url, content_folder)
        if is_ok:
            info["preview_path"] = result
        else:
            print("Cannot get preview from:", preview_url)
            print(result)

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

    dimensions = {}

    x = meta.get("length")
    if x:
        x = float(number_pattern.search(x).group(0))
    y = meta.get("width")
    if y:
        y = float(number_pattern.search(y).group(0))

    if not x and not y:
        scan_area = meta.get("scanArea")
        if not scan_area:
            sizes = utils.locate_item(mega_info, "physicalSize", is_dict_key=True, return_as='data')
            if sizes:
                scan_area = Counter(sizes).most_common(1)[0][0]
        if scan_area:
            sizes = number_pattern.findall(scan_area)
            if len(sizes) == 2:
                x = float(sizes[0])
                y = float(sizes[1])
            elif len(sizes) == 1:
                x = y = float(sizes[0])
                
    if x:
        dimensions['x'] = x
    if y:
        dimensions['y'] = y
            
    z = meta.get("height")
    if z:
        dimensions['z'] = float(number_pattern.search(z).group(0))

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

    utils.remove_empty(info)
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
    "dimensions": {},
}
info["preview_path"] = ""
'''

INFO_SUPPORTED_SITES = {
    "sketchfab.com": get_web_sketchfab_info,
    "blendswap.com": get_web_blendswap_info,
    "source.substance3d.com": get_web_substance_source_info,
    "substance3d.adobe.com": get_web_substance_source_info,
    "quixel.com": get_web_megascan_info,

    "polyhaven.com": get_web_polyhaven_info,

    "cc0textures.com": get_web_ambientcg_info,
    "cc0.link": get_web_ambientcg_info,
    "ambientcg.com": get_web_ambientcg_info,
}

ASSET_SUPPORTED_SITES = {
    "polyhaven.com": get_web_polyhaven_asset,

    "cc0textures.com": get_web_ambientcg_asset,
    "ambientcg.com": get_web_ambientcg_asset,
    "cc0.link": get_web_ambientcg_asset
}

def get_web(url: str, content_folder = None, as_asset = False) -> typing.Tuple[bool, dict]:
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
