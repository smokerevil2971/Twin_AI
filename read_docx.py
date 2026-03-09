import zipfile
import xml.etree.ElementTree as ET
try:
    z = zipfile.ZipFile(r'd:\rakesh project\Twin_AI\resources\Two_Bot_Implementation_Plan.docx')
    t = ET.fromstring(z.read('word/document.xml'))
    texts = []
    for p in t.iter():
        if p.tag.endswith('}p'):
            t_str = ''.join(n.text for n in p.iter() if n.tag.endswith('}t') and n.text)
            if t_str.strip():
                texts.append(t_str.strip())
    with open(r'd:\rakesh project\Twin_AI\plan_text.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(texts))
    print('Extraction complete')
except Exception as e:
    print('Error:', e)
