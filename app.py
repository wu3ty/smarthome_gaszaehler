from flask import Flask
from flask import send_file
from flask import abort

import json
import numpy as np
from skimage import exposure
from skimage import io    
from skimage import transform
import requests
from PIL import Image
from skimage.filters import unsharp_mask

import easyocr

import logging
import os.path
from datetime import datetime

logging.basicConfig(filename="gas.log",
                    filemode='a',
                    format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)

logging.info("Running Gas Reading API")


CAPTURE_URL = "http://192.168.2.106/capture"
CURRENT_CAPTURE_FILE = 'current_1_capture_raw.jpg'
CURRENT_WARP_FILE = 'current_2_warped.jpg'
CURRENT_SHARPENED_FILE = 'current_3_sharpened.jpg'
CURRENT_FILTERED_FILE = 'current_4_filtered.jpg'
DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S"
LAST_READING_FILENAME = 'last_reading.json'
IMAGE_PATH = "./debug/"

source_height = 156
source_digit_width= 50

def extract_image_digit(_image, digit):
    # offsets: 0, 95, 195, 295, 390, 485, 585, 705
    x_offset = 0
    if digit == 1:
        x_offset = 0
    elif digit == 2:
        x_offset = 95
    elif digit == 3:
        x_offset = 195
    elif digit == 4:
        x_offset = 295
    elif digit == 5:
        x_offset = 390
    elif digit == 6:
        x_offset = 485
    elif digit == 7:
        x_offset = 585
    elif digit == 8:
        x_offset = 705
    else:
        raise ValueError("Digit needs to be in {1,...,8}")
    
    digit_width = source_height / 2
    digit_height = source_height

    src = np.array([[0, 0], [0, digit_height], [digit_width, digit_height], [digit_width, 0]])

    # Oben L., Unten L., Unten R., Oben R.
    dst = np.array([[x_offset, 0], [x_offset, source_height], [x_offset + source_digit_width, source_height], [x_offset + source_digit_width, 0]])

    tform3 = transform.ProjectiveTransform()
    tform3.estimate(src, dst)
    image_warped = transform.warp(_image, tform3, output_shape=(digit_height, digit_width))        

    return image_warped

def read_current_reading():
    logging.info(f"Downloading image from {CAPTURE_URL}")
    img_data = requests.get(CAPTURE_URL).content
    with open(CURRENT_CAPTURE_FILE, 'wb') as handler:
        handler.write(img_data)

    image = io.imread(CURRENT_CAPTURE_FILE, as_gray=True)    
    image = image[:, ::-1]
    #image.shape # => (600, 800)

    # extract reading picture
    logging.info(f"Extracting image")
    target_width = 780
    target_height = target_width / 5

    src = np.array([[0, 0], [0, target_height], [target_width, target_height], [target_width, 0]])

    # Oben L., Unten L., Unten R., Oben R.
    right_x = 880
    dst = np.array([[130, 380], [130, 455], [right_x, 460], [right_x, 390]])

    tform3 = transform.ProjectiveTransform()
    tform3.estimate(src, dst)
    image_warped = transform.warp(image, tform3, output_shape=(target_height, target_width))

    # save picture
    int_image = (255 * image_warped).astype(np.uint8)
    io.imsave(CURRENT_WARP_FILE, int_image)
    
    # sharpen
    logging.info(f"Sharp image")
    sharpened = unsharp_mask(int_image, radius=300, amount=2)
    int_sharpened = (255 * sharpened).astype(np.uint8)
    io.imsave(CURRENT_SHARPENED_FILE, int_sharpened)
    # io.imshow(int_sharpened)

    # Filtering by selecting only highest percentile values
    logging.info(f"Filter image for high contract")
    p_low, p_high = np.percentile(int_sharpened, (82, 100))
    img_contrast = exposure.rescale_intensity(int_sharpened, in_range=(p_low, p_high))
    
    io.imsave(CURRENT_FILTERED_FILE, img_contrast)

    # extract individual digit images
    logging.info(f"Extracting individual digit images")
    for digit in range(1, 9):
        filename = f"current_digit_{digit}.png"
        image_digit = extract_image_digit(img_contrast, digit)

        im = Image.fromarray((image_digit * 255).astype('uint8'), mode='L')
        #im.show()
        im.save(filename)    

    logging.info(f"OCRing digits")
    reading_str = ""
    

    USE_DIGITS = 7

    reader = easyocr.Reader(['en']) # this needs to run only once to load the model into memory    
    for digit in range(1, USE_DIGITS + 1):
        filename = f"current_digit_{digit}.png"
        #  PSM 10|single_char             Treat the image as a single character.
        # OEM: OCR Engine modes (OEM):  3|default                 Default, based on what is available.

        result = reader.readtext(filename, allowlist ='0123456789')
        if not result:
            raise ValueError(f"Nothing found for digit {digit}")
        max_conf = -1
        raw_text = None
        for res in result:
            if res[2] > max_conf:
                max_conf = res[2]
                raw_text = res[1]
        logging.debug(f"Digit {digit}: '{raw_text}'")
        character = raw_text.replace("\n", "")

        if len(character) != 1:
            raise ValueError(f"Invalid reading \'{character}\' for digit {digit}, check {filename}")
        
        if digit == 6:
            reading_str += "."

        reading_str += character
        #print(text)

    # remove trailing 0s 
    reading_str = reading_str.rstrip("0")

    meter_reading = float(reading_str)
    assert reading_str == str(meter_reading), f"converted {reading_str} to float {meter_reading} does not match"
    logging.info(f"Current meter reading: {meter_reading}")
    return meter_reading



app = Flask(__name__)

@app.route('/gas/digit/<digit>')
def gas_digit(digit):
    filename = f"current_digit_{digit}.png"
    if os.path.isfile(filename):
        return send_file(filename, mimetype='image/png')

    return abort(404)

@app.route('/gas/picture')
def gas_picture():
    if os.path.isfile(CURRENT_FILTERED_FILE):
        return send_file(CURRENT_FILTERED_FILE, mimetype='image/png')

    return abort(404)

@app.route('/gas/raw')
def gas_raw():
    if os.path.isfile(CURRENT_CAPTURE_FILE):
        return send_file(CURRENT_CAPTURE_FILE, mimetype='image/png')

    return abort(404)

@app.route('/gas/current')
def gas_current():
    current_reading = None
    try:
        current_reading = read_current_reading()
    except Exception as ex:
        logging.error(f"Issue reading gas meter: {ex}")
        return abort(400)

    data = {
        'current': current_reading,
        'time': datetime.now().strftime(DATETIME_FORMAT)
        }
    
    # perform validity check; open last file and check delta
    if os.path.isfile(LAST_READING_FILENAME):
        with open(LAST_READING_FILENAME) as f:
            d = json.load(f)
            
            last_gas_reading = d["current"]
            if current_reading < last_gas_reading:
                logging.error(f"Current reading of {current_reading} is smaller than previous reading of {last_gas_reading} from {d['time']}")
                return abort(400)
            if abs(current_reading - last_gas_reading) > 100:
                logging.error(f"Current reading of {current_reading} is much larger than previous reading of {last_gas_reading} from {d['time']}")
                return abort(400)
    
    # save last reading to file
    with open(LAST_READING_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return json.dumps(data)

if __name__ == '__main__':
   app.run(debug=True)