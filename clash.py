import logging
import os
import json
import zipfile
import base64
import shutil
import xml.etree.ElementTree as ET
import concurrent.futures
from ifcclash.ifcclash import Clasher, ClashSettings


def detect_clashes(clash_sets, bcf_file_path):
    """
    Perform clash detection based on the provided clash sets and export to BCF.
    Returns the raw clash data (including exact coordinates).
    """
    settings = ClashSettings()
    settings.logger = logging.getLogger("Clash")
    settings.logger.setLevel(logging.DEBUG)
    settings.output = bcf_file_path

    # Initialize clasher and execute the process
    clasher = Clasher(settings)
    clasher.clash_sets = clash_sets
    clasher.clash()

    # BCF를 먼저 내보냅니다.
    clasher.export_bcfxml()

    # clasher.clash_sets에는 이미 'p1' (Clash Point) 좌표 정보가 포함되어 있습니다.
    # 이를 반환하여 후처리 단계에서 정확한 좌표 매핑에 사용합니다.
    total_clashes_initial = sum(len(cs.get("clashes", [])) for cs in clasher.clash_sets)

    print(f"""
    Initial clash detection complete. BCF created at: {bcf_file_path}
    Found potential clashes: {total_clashes_initial}
    """)
    
    return clasher.clash_sets


def post_process_bcf(bcf_file_path, raw_clash_data=None):
    """
    Post-process the BCF package to standardize filenames and inject snapshots.
    Also extracts exact clash point coordinates to a JSON file.
    """
    temp_dir = bcf_file_path + "_extracted"
    
    # 1. Decompress the BCF package
    if not os.path.exists(bcf_file_path):
        print(f"Error: BCF file not found at {bcf_file_path}")
        return
    
    # --- Build Clash Point Lookup Map ---
    # GUID 쌍(Set)을 키로 사용하여 순서에 상관없이 좌표를 찾을 수 있게 합니다.
    clash_point_map = {}
    if raw_clash_data:
        for cs in raw_clash_data:
            if "clashes" in cs:
                for clash in cs["clashes"].values():
                    # frozenset을 사용하여 guid1-guid2 순서와 무관하게 매칭
                    key = frozenset([clash["a_global_id"], clash["b_global_id"]])
                    clash_point_map[key] = clash["p1"]

    extracted_data = []  # JSON으로 저장할 데이터 리스트

    with zipfile.ZipFile(bcf_file_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    # 최적화 1: base64 디코딩을 반복문 외부에서 1회만 수행
    dummy_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

    def process_topic(topic_guid):
        topic_path = os.path.join(temp_dir, topic_guid)
        if not os.path.isdir(topic_path): 
            return None
            
        clash_set_name = "Unknown"
        guids = []
        clash_point = None

        # A. BCFV 파싱, 정보 추출 및 XML 수정 (최적화 2: 파싱 1회로 통합)
        bcfv_files = [f for f in os.listdir(topic_path) if f.endswith(".bcfv")]
        for f in bcfv_files:
            old_bcfv = os.path.join(topic_path, f)
            new_bcfv = os.path.join(topic_path, "viewpoint.bcfv")
            if old_bcfv != new_bcfv:
                if os.path.exists(new_bcfv): os.remove(new_bcfv)
                os.rename(old_bcfv, new_bcfv)
                
        new_bcfv = os.path.join(topic_path, "viewpoint.bcfv")
        if os.path.exists(new_bcfv):
            try:
                v_tree = ET.parse(new_bcfv)
                v_root = v_tree.getroot()
                
                for elem in v_root.iter():
                    if elem.tag.endswith("Component") and "IfcGuid" in elem.attrib:
                        if elem.attrib["IfcGuid"] not in guids:
                            guids.append(elem.attrib["IfcGuid"])
                            
                components_node = v_root.find("Components")
                if components_node is not None:
                    selection_node = components_node.find("Selection")
                    component_guids = [] if selection_node is None else [comp.attrib["IfcGuid"] for comp in selection_node.findall("Component") if "IfcGuid" in comp.attrib]

                    existing_coloring = components_node.find("Coloring")
                    if existing_coloring is not None:
                        components_node.remove(existing_coloring)

                    coloring_node = ET.SubElement(components_node, "Coloring")
                    color_a = ET.SubElement(coloring_node, "Color", {"Color": "B3FF0000"})
                    color_b = ET.SubElement(coloring_node, "Color", {"Color": "B300FF00"})

                    if len(component_guids) >= 2:
                        ET.SubElement(color_a, "Component", {"IfcGuid": component_guids[0]})
                        ET.SubElement(color_b, "Component", {"IfcGuid": component_guids[1]})
                        
                v_tree.write(new_bcfv, encoding="utf-8", xml_declaration=True)
            except Exception:
                pass

        # B. markup.bcf 파싱, 정보 추출 및 XML 수정 (최적화 3: 파싱 1회로 통합)
        markup_path = os.path.join(topic_path, "markup.bcf")
        if os.path.exists(markup_path):
            try:
                m_tree = ET.parse(markup_path)
                m_root = m_tree.getroot()
                for elem in m_root.iter():
                    if elem.tag.endswith("Title"):
                        clash_set_name = elem.text
                        break
                        
                viewpoints_node = m_root.find("Viewpoints")
                if viewpoints_node is not None:
                    for child in list(viewpoints_node):
                        viewpoints_node.remove(child)
                    viewpoint = ET.SubElement(viewpoints_node, "Viewpoint")
                    viewpoint.text = "viewpoint.bcfv"
                    snapshot = ET.SubElement(viewpoints_node, "Snapshot")
                    snapshot.text = "snapshot.png"
                    
                m_tree.write(markup_path, encoding="utf-8", xml_declaration=True)
            except Exception:
                pass

        # C. Snapshot 이미지 생성
        target_png = os.path.join(topic_path, "snapshot.png")
        with open(target_png, "wb") as f:
            f.write(dummy_png)

        # D. P1 정보 매핑
        if len(guids) >= 2:
            key = frozenset([guids[0], guids[1]])
            clash_point = clash_point_map.get(key)

        return {
            "clash_set": clash_set_name,
            "clash_guid": topic_guid,
            "guid1": guids[0] if len(guids) > 0 else None,
            "guid2": guids[1] if len(guids) > 1 else None,
            "clash_point": clash_point
        }

    # 최적화 4: I/O 바운드 작업인 폴더 처리를 멀티스레드로 병렬 처리
    topics = os.listdir(temp_dir)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for result in executor.map(process_topic, topics):
            if result is not None:
                extracted_data.append(result)

    # 3. Save extracted data to JSON
    json_output_path = os.path.splitext(bcf_file_path)[0] + "_clashes.json"
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=4, ensure_ascii=False)

    # 4. Re-compress the structure back into a BCF package
    with zipfile.ZipFile(bcf_file_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                new_zip.write(full_path, rel_path)

    # 5. Cleanup: Remove temporary extraction directory
    shutil.rmtree(temp_dir)
    total_clashes = len(extracted_data)
    
    print(f"""\
    Final BCF package created: {bcf_file_path}
    Clash data saved to: {json_output_path}
    """)
    
    return bcf_file_path, json_output_path

if __name__ == "__main__":
    ## Input Parameters
    bcf_file_path = r"D:\\02-Dev\\0203_Dev-IfcClash\\clash-detection.bcf"

    ## Define clash matrix
    input_file = r"D:\\02-Dev\\0203_Dev-IfcClash\\input.json"
    with open(input_file, "r") as clash_sets_file:
       clash_sets = json.loads(clash_sets_file.read())

    ## Function Execution
    # 원본 데이터(raw_clash_data)를 받아서 post_process_bcf에 전달
    raw_clash_data = detect_clashes(clash_sets, bcf_file_path)
    post_process_bcf(bcf_file_path, raw_clash_data)
