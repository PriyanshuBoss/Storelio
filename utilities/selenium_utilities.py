import time
import logging
import traceback

from django.conf import settings
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from saleor.store.states import LinktreeType

logger = logging.getLogger(__name__)


class WebCrawl:
    max_wait = 10

    @staticmethod
    def get_default_chrome_options():
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--incognito")
        chrome_options.add_argument("--window-size=1920x1080")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--headless")
        return chrome_options

    @classmethod
    def get_default_web_driver(cls):
        chromedriver = settings.CHROMEDRIVER_PATH
        driver = webdriver.Chrome(chromedriver, options=cls.get_default_chrome_options())
        return driver
    
    @classmethod
    def find_elements_by_id(cls, driver, id):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.ID, id))
                )
        
            elements = driver.find_elements(by=By.ID, value=id)
            return elements
        except Exception as e:
            return []
    
    @classmethod
    def get_element_text_by_xpath(cls, driver, xpath):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            elements = driver.find_elements(by=By.XPATH, value=xpath)
            return elements[0].get_attribute('text') or ''
        except Exception as e:
            return ''

    @classmethod        
    def find_elements_by_css_selector(cls, driver, selector):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
        
            elements = driver.find_elements(by=By.CSS_SELECTOR, value=selector)
            return elements
        except Exception as e:
            return []

    @classmethod
    def get_element_by_css_selector(cls, driver, selector):
        try:
            elements = cls.find_elements_by_css_selector(driver, selector)
            return elements[0]
        except Exception as e:
            return None
    
    @classmethod
    def get_img_src_by_css_selector(cls, driver, selector):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
            element = driver.find_elements(by=By.CSS_SELECTOR, value=selector)[0]
            src = element.get_attribute('src') or ''
            return src
        except Exception as e:
            return ''
    
    @classmethod
    def get_element_attribute_by_css_selector(cls, driver, selector, attr='href'):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
            element = driver.find_elements(by=By.CSS_SELECTOR, value=selector)[0]
            attribute = element.get_attribute(attr)
            return attribute or ''
        except Exception as e:
            return ''

    @classmethod
    def get_element_attribute_by_id(cls, driver, id, attr='href'):
        try:
            wait = WebDriverWait(driver, cls.max_wait).until(
                    EC.presence_of_element_located((By.ID, id))
                )
            element = driver.find_elements(by=By.ID, value=id)[0]
            attribute = element.get_attribute(attr)
            return attribute or ''
        except Exception as e:
            return ''    


class LinktreeCrawl:

    session_start = True

    @staticmethod
    def start(linktree_link):
        driver = WebCrawl.get_default_web_driver()
        rows = LinktreeCrawl.linktree_crawl(driver, linktree_link)
        logger.info(f"linktree crawl:: found {len(rows)} links")
        for idx, row in enumerate(rows):
            logger.info(f"linktree crawl:: {idx} {row.get('link')}")
            if row['type'] == LinktreeType.OTHER and row.get('link'):
                driver.get(row.get('link'))
                time.sleep(5)
                row['link'] = driver.current_url
                row['type'] = LinktreeType.get_type(row['link'])

            if row['type'] == LinktreeType.LINKTREE:
                continue

            method_name = '_'.join([row['type'], 'crawl'])
            if not hasattr(LinktreeCrawl, method_name):
                continue
            method = getattr(LinktreeCrawl, method_name)
            src, link_type = method(driver, row.get('link'))
            if src != 'invalid_url':
                logger.info(f"linktree crawl src:: {idx} {src}")
                row['img_src'] = src or row.get('img_src')
                row['type'] = link_type

        driver.quit()  
        return rows

    @staticmethod
    def linktree_crawl(driver, linktree_link):
        profile = ''
        bio = ''
        rows = []
        try:
            driver.get(linktree_link)
            time.sleep(5)
            profile = WebCrawl.get_img_src_by_css_selector(driver, "img[data-testid='ProfileImage']")
            bio_header = WebCrawl.get_element_by_css_selector(driver, "h2")
            if bio_header:
                bio = bio_header.text
            rows.append({
                'title': bio,
                'link': linktree_link,
                'img_src': profile,
                'type': LinktreeType.LINKTREE
            })

            social_links = WebCrawl.find_elements_by_css_selector(driver, "a[data-testid='SocialIcon']")
            for social_link in social_links:
                link = social_link.get_attribute('href')
                rows.append({
                    'title': social_link.get_attribute('aria-label'),
                    'link': link,
                    'img_src': '',
                    'type': LinktreeType.get_type(link, return_account=True)
                })

            elements = WebCrawl.find_elements_by_css_selector(driver, "div[data-testid='StyledContainer']")
            for element in elements:
                title = element.text
                link = WebCrawl.get_element_attribute_by_css_selector(element, "a[data-testid='LinkButton']", attr='href')
                img_src = WebCrawl.get_img_src_by_css_selector(element, "img[data-testid='LinkThumbnailImage']")
                if 'linktr.ee/' in img_src:
                    img_src = img_src.split('?')[0]
                
                row = {
                    'title': title,
                    'link': link,
                    'img_src': img_src,
                    'type': LinktreeType.get_type(link)
                }
                rows.append(row)
        except Exception:
            logger.info(f"Linktree crawl error:: {traceback.format_exc()}")
        
        return rows

    @staticmethod
    def youtube_crawl(driver, url):
        if not 'youtube' in url:
            invalid = ('invalid_url', None)
            return invalid
        if not 'watch?v=' in url.lower():
            url = url.split('?')[0]
        profile = ''
        driver.get(url)
        time.sleep(5)
        if LinktreeCrawl.session_start:
            try:
                # reject_all = find_elements_by_css_selector(driver, "#yDmH0d > c-wiz > div > div > div > div.NIoIEf > div.G4njw > div.qqtRac > div.VtwTSb > form:nth-child(2) > div > div > button > span")[0].click()
                accept_all = WebCrawl.find_elements_by_css_selector(driver, "#yDmH0d > c-wiz > div > div > div > div.NIoIEf > div.G4njw > div.qqtRac > div.VtwTSb > form:nth-child(3) > div > div > button > span")[0].click()
                time.sleep(2)
                LinktreeCrawl.session_start = False
            except Exception as e:
                pass
        profile = WebCrawl.get_element_attribute_by_id(driver, "img", attr="src")
        if '-c-k-' in profile:
            first, last = profile.split('-c-k-')
            profile = first.rsplit('=', 1)[0] + '=s0-c-k-' + last 

        return profile, LinktreeType.get_type(url)

    @staticmethod
    def snapchat_crawl(driver, url):
        if not 'snapchat' in url:
            invalid = ('invalid_url', None)
            return invalid
        url = url.split('?')[0]
        driver.get(url)
        time.sleep(5)
        profile = WebCrawl.get_img_src_by_css_selector(driver, "img[alt='Profile Picture']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "#__next > div.UserProfile_desktopContainer__Sr1QZ > main > div.DesktopUserProfile_desktopContainer__c4Yof > div.UserCard_container__dd60C > div.UserCard_bitmojiWrapperDesktop__Y8lcW > div > div.Bitmoji3DImage_webPImageWrapper___Ve_9.Bitmoji3DImage_avatarImageStyle__3A2Bz > picture > img")
        # profile = profile or get_img_src_by_css_selector(driver, "img[data-testid='snapcode']")
        if '_RS0,' in profile and '_FM' in profile:
            profile = profile.split('_RS0,')[0] + '_FM' + profile.split('_FM')[-1]

        return profile, LinktreeType.get_type(url)

    @staticmethod
    def pinterest_crawl(driver, url):
        if not 'pin.it' in url:
            invalid = ('invalid_url', None)
            return invalid
        url = url.split('?')[0]
        driver.get(url)
        time.sleep(5)
        profile = WebCrawl.get_img_src_by_css_selector(driver, "img[alt='User Avatar']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "img[elementtiming='closeupImage']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(WebCrawl.get_element_by_css_selector(driver, "div[data-test-id='gestalt-avatar-svg']"), "img")
        if '_RS' in profile:
            first, last = profile.split('_RS/')
            profile = first.rsplit('/', 1)[0] + '/736x/' + last

        return profile, LinktreeType.PINTEREST
    
    @staticmethod
    def hypd_crawl(driver, url):
        if not 'hypd' in url:
            invalid = ('invalid_url', None)
            return invalid
        profile = ''
        driver.get(url)
        time.sleep(5)
        try:
            wait = WebDriverWait(driver, 5).until(
                    EC.alert_is_present()
                )
            alert = driver.switch_to.alert
            alert.accept()
            driver.back()
            return '', LinktreeType.get_type(url)
        except Exception as e:
            pass

        if 'product?id=' in url or 'product/' in url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#app > div > div > div.product-description-section.screen-container > div:nth-child(1) > div > div.active-image > div > figure > img")
        elif 'brand' in url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#brand-page-section > div.screen-container > div > div.profile-wrapper > div.display-picture > img") 
        elif 'collection' in url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#brand-page-section > div.flex-together.collection-info.gap-14 > img")
            profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "#brand-page-section > div.flex-together.collection-info.gap-14 > div.default-image > img:nth-child(1)")
        if not profile:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#creator-store-section-hide > div:nth-child(2) > div.creator-info > div.creator-info-container.desktop > div.creator-dp > img")
        
        for size in ('100', '150', '350'):
            profile = profile.replace(f'height={size}', 'height=800')
            profile = profile.replace(f'{size}x{size}', '800x800')
        return profile, LinktreeType.get_type(url)
    
    @staticmethod
    def wishlink_crawl(driver, url):
        if not 'wishlink' in url:
            invalid = ('invalid_url', None)
            return invalid
        driver.get(url)
        time.sleep(5)
        current_url = driver.current_url
        profile = ''
        if '/post' in current_url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#root > div > div > div > div:nth-child(1) > div:nth-child(2) > div > div.MuiCardMedia-root.post-slider.css-dhpz8w > div > div > div > div > div > div > a > img")
        elif 'allpost' in current_url:
            element = WebCrawl.get_element_by_css_selector(driver, "#root > div > div > div > div.background-theme-light > div > div:nth-child(2) > div > div:nth-child(5) > div > div:nth-child(1) > div > a > div > div.lazyload-wrapper > div")
            try:
                url = element.get_attribute('style')
                profile = url.split('"')[1]
            except Exception as e:
                pass
        elif 'collection' in current_url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "div.MuiCardMedia-root.jss20.css-pqdqbj > img")
        elif 'getketch' in current_url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "div.product-imageSingle > img")
        elif 'myntra' in current_url:
            element = WebCrawl.get_element_by_css_selector(driver, "div.image-grid-image")
            try:
                url = element.get_attribute('style')
                profile = url.split('"')[1]
            except Exception as e:
                pass
        elif 'meesho' in current_url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "#__next > div.sc-jOiSOi.Pagestyled__ContainerStyled-sc-ynkej6-0.bwNoFa.eQYgmX > div > div.sc-bCfvAP.jspZBG > div > div.sc-bcXHqe.cEPbjl.ProductCard__Container-sc-camkhj-0.ihYaVC.ProductCard__Container-sc-camkhj-0.ihYaVC > div.ProductDesktopImage__ImageWrapperDesktop-sc-8sgxcr-0.iEMJCd > img")
        elif 'amazon' in current_url:
            profile = LinktreeCrawl.amazon_crawl(driver, current_url)
        else:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "img[alt='Creator DP']")

        return profile, LinktreeType.get_type(current_url)
    
    @staticmethod
    def amazon_crawl(driver, url):
        if not 'amazon' in url:
            invalid = ('invalid_url', None)
            return invalid
        driver.get(url)
        time.sleep(5)
        profile = ''
        redirect = WebCrawl.get_element_by_css_selector(driver, "body > div > div.page.-cx-PRIVATE-Page__body.-cx-PRIVATE-Page__body__ > div > div > p:nth-child(3) > button")
        if redirect:
            redirect.click()
            time.sleep(3)
        if 'music' in url:
            profile = WebCrawl.get_img_src_by_css_selector(driver, "div > div.left > div > music-image")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "img[class='photo-spv-image']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "img[id='shop-influencer-profile-image']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "img[id='shop-influencer-profile-header-image']")
        profile = profile or WebCrawl.get_img_src_by_css_selector(driver, "img[id='landingImage']")

        return profile, LinktreeType.get_type(url)