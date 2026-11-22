/* Kachra Mitra — no build step, no framework. Read top to bottom. */
(() => {
  "use strict";

  // ---------------------------------------------------------------- config
  const OVERRIDE = localStorage.getItem("waste.apiBase");
  const DEPLOYED = (window.WASTE_API_BASE || "").trim().replace(/\/$/, "");
  const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  // When the page is served by the API itself (http://127.0.0.1:8000/app/) talk to that
  // same server. Otherwise a local dev session would call the hosted Render URL, which
  // can take ~50 s to wake from sleep — long enough that every scan looks broken.
  const SERVED_BY_API = LOCAL_HOST && location.pathname.startsWith("/app");
  const API = (OVERRIDE || (SERVED_BY_API ? location.origin : DEPLOYED)
    || (location.protocol.startsWith("http") ? location.origin : "http://127.0.0.1:8000"))
    .replace(/\/$/, "");
  const DEFAULT_CENTER = [19.076, 72.8777]; // Mumbai — demo fallback only

  // ---------------------------------------------------------------- i18n
  const STR = {
    en: {
      "app.name": "Kachra Mitra",
      "app.tagline": "Scan it. Sort it. Dispose of it right.",
      "scan.title": "What are you throwing away?",
      "scan.subtitle": "Take a photo or upload one. We will tell you the bin, the steps and the safety warnings.",
      "scan.camera": "Take photo",
      "scan.upload": "Upload",
      "scan.addDetails": "Add a description (optional, improves accuracy)",
      "scan.hintLabel": "Description",
      "scan.hintPlaceholder": "e.g. old Nokia charger, broken tube light",
      "scan.barcodePlaceholder": "Barcode (optional)",
      "scan.analyse": "Scan item",
      "scan.point": "Point at a waste item",
      "scan.center": "Keep one item inside the frame — good light, clean background.",
      "scan.gallery": "Gallery",
      "scan.cameraShort": "Camera",
      "scan.ai": "AI scan",
      "scan.scanning": "Scanning…",
      "scan.more": "Barcode",
      "scan.resultLabel": "Scan result",
      "scan.tap": "Tap the shutter to identify",
      "scan.dismiss": "Collapse result",
      "scan.waking": "Waking the server…",
      "scan.woke": "The server was asleep — it took {s}s. The next scans are fast.",
      "scan.compressed": "Photo compressed for upload",
      "chat.title": "Ask Kachra Mitra",
      "chat.new": "New chat",
      "chat.subtitle": "Rules, bins, composting, e-waste, batteries — in your language.",
      "chat.chip1": "Broken tube light",
      "chat.chip2": "Composting in a flat",
      "chat.chip3": "Chips packet",
      "chat.chip4": "Swollen battery",
      "chat.q1": "Which bin does a broken tube light go in?",
      "chat.q2": "Can I compost vegetable peels at home in a flat?",
      "chat.q3": "Is a chips packet recyclable?",
      "chat.q4": "What should I do with a swollen phone battery?",
      "chat.placeholder": "Ask about an item or a rule…",
      "chat.send": "Send",
      "chat.disclaimer": "General guidance, not legal advice. Verify local rules with your municipal corporation.",
      "map.title": "Where to drop it off",
      "map.subtitle": "A live Google Map of places near you. Directions open in Google Maps.",
      "map.category": "Category",
      "map.locate": "Use my location",
      "history.title": "Your impact",
      "history.subtitle": "Scans are stored without images — only the item and category.",
      "history.subtitleImages": "Scan photos are stored in Cloudinary; the item and category are stored in the app database.",
      "history.scans": "Scans",
      "history.points": "Eco points",
      "history.categories": "Categories",
      "history.refresh": "Refresh",
      "nav.scan": "Scan",
      "nav.chat": "Chat",
      "nav.map": "Map",
      "nav.history": "Impact",
      "auth.login": "Log in",
      "auth.signup": "Create account",
      "auth.logout": "Log out",
      "auth.email": "Email",
      "auth.password": "Password",
      "auth.name": "Name",
      "auth.titleIn": "Log in",
      "auth.titleUp": "Create account",
      "auth.blurb": "Sign in to keep your scans on your account.",
      "auth.need": "New here? Create an account",
      "auth.have": "Already have an account? Log in",
      "auth.admin": "Admin",
      "auth.openAdmin": "Open admin dashboard",
      "auth.signedIn": "You are signed in.",
      "auth.guest": "Guest scans stay on this device until you log in.",
      "auth.accountLine": "Signed in as {name}",
      "auth.close": "Close",
      "map.openArea": "Open this area in Google Maps",
      "map.showRoute": "Show route",
      "map.openDir": "Open directions",

      greeting: "Namaste! Ask me about any waste item, a bin colour, composting, or where to drop something off.",
      analysing: "Looking at your photo…",
      errImage: "Please choose an image first.",
      errGeneric: "Something went wrong. Please try again.",
      errNetwork: "Cannot reach the server. Is the backend running on " + API + "?",
      errTimeout: "The server took too long to answer. Please try again.",
      errLarge: "That image is too large. Try a smaller photo.",
      confidence: "Confidence",
      uncertain: "Low confidence — check the item name and the alternatives below.",
      other: "Other possibilities",
      bin: "Put it here",
      steps: "What to do",
      avoid: "Avoid",
      rules: "Rules",
      findDropoff: "Find a drop-off point",
      askAbout: "Ask about this item",
      scanAgain: "Scan another item",
      correct: "Correct",
      wrong: "Wrong item",
      feedbackThanks: "Thanks — that helps improve the model.",
      chooseCorrect: "Which item was it?",
      submit: "Submit",
      points: "+{n} eco points",
      scanSaved: "Scan saved.",
      chatThinking: "Thinking…",
      chatError: "I could not reach the assistant. The rule cards still work — try the Scan tab.",
      sources: "Sources",
      trace: "How I answered",
      chatFacilities: "Collection points mentioned",
      nearby: "Nearby collection points",
      directions: "Directions",
      sampleData: "Sample data for the demo — set FACILITY_PROVIDER=overpass for live OpenStreetMap results.",
      cached: "Live search failed, so these are cached results.",
      live: "Live places near you. The map is Google Maps; directions open there too.",
      noFacilities: "No collection points found nearby. Try a larger radius or check your municipal corporation helpline.",
      locating: "Finding your location…",
      locationDenied: "Your location is unavailable. Allow location access in your browser, then reload the map. No demo locations are shown.",
      demoLocation: "Showing the demo area (Mumbai).",
      historyEmpty: "No scans yet. Scan something to start.",
      loading: "Loading…",
      stepsNote: "Disposal steps are shown in English; ask in the Chat tab for a translation.",
      barcode: "Product (from barcode)",
      packagingHint: "Packaging hint",
      attach: "Photo attached",
      remove: "Remove",
      scanPointsAwarded: "You earned {n} eco points.",
      of: "of",
      topMatches: "Top matches",
      mapHint: "Tap a pin for details.",
      helpline: "If you cannot find a point, call your municipal corporation's waste helpline.",
      cat_ewaste: "E-waste",
      cat_recyclable: "Recyclable",
      cat_general: "General",
      cat_organic: "Organic",
      cat_hazardous: "Hazardous",
      cat_biomedical: "Biomedical"
    },
    hi: {
      "app.name": "कचरा मित्र",
      "app.tagline": "स्कैन करें, छाँटें, सही जगह डालें।",
      "scan.title": "आप क्या फेंक रहे हैं?",
      "scan.subtitle": "फोटो लें या अपलोड करें। हम डिब्बा, तरीका और सुरक्षा चेतावनी बताएँगे।",
      "scan.camera": "फोटो लें",
      "scan.upload": "अपलोड",
      "scan.addDetails": "विवरण जोड़ें (वैकल्पिक, सटीकता बढ़ाता है)",
      "scan.hintLabel": "विवरण",
      "scan.hintPlaceholder": "जैसे पुराना नोकिया चार्जर, टूटी ट्यूबलाइट",
      "scan.barcodePlaceholder": "बारकोड (वैकल्पिक)",
      "scan.analyse": "वस्तु स्कैन करें",
      "scan.point": "कचरे की वस्तु पर कैमरा रखें",
      "scan.center": "एक वस्तु फ्रेम में रखें — अच्छी रोशनी, साफ़ पृष्ठभूमि।",
      "scan.gallery": "गैलरी",
      "scan.cameraShort": "कैमरा",
      "scan.ai": "एआई स्कैन",
      "scan.scanning": "स्कैन हो रहा है…",
      "scan.more": "बारकोड",
      "scan.resultLabel": "स्कैन परिणाम",
      "scan.tap": "पहचानने के लिए शटर दबाएँ",
      "scan.dismiss": "परिणाम छोटा करें",
      "scan.waking": "सर्वर शुरू हो रहा है…",
      "scan.woke": "सर्वर सो रहा था — {s} सेकंड लगे। अगली स्कैन तेज़ होंगी।",
      "scan.compressed": "अपलोड के लिए फ़ोटो छोटी की गई",
      "chat.title": "कचरा मित्र से पूछें",
      "chat.new": "नई चैट",
      "chat.subtitle": "नियम, डिब्बे, खाद, ई-कचरा, बैटरी — आपकी भाषा में।",
      "chat.chip1": "टूटी ट्यूबलाइट",
      "chat.chip2": "फ्लैट में खाद",
      "chat.chip3": "चिप्स का पैकेट",
      "chat.chip4": "फूली हुई बैटरी",
      "chat.q1": "टूटी ट्यूबलाइट किस डिब्बे में डालनी चाहिए?",
      "chat.q2": "क्या मैं फ्लैट में घर पर सब्ज़ियों के छिलकों की खाद बना सकता हूँ?",
      "chat.q3": "क्या चिप्स का पैकेट रीसायकल हो सकता है?",
      "chat.q4": "फूली हुई फोन बैटरी का क्या करें?",
      "chat.placeholder": "किसी वस्तु या नियम के बारे में पूछें…",
      "chat.send": "भेजें",
      "chat.disclaimer": "यह सामान्य मार्गदर्शन है, कानूनी सलाह नहीं। स्थानीय नियम नगर निगम से जाँचें।",
      "map.title": "कहाँ जमा करें",
      "map.subtitle": "आपके पास का लाइव Google नक्शा। रास्ता Google Maps में खुलता है।",
      "map.category": "श्रेणी",
      "map.locate": "मेरी लोकेशन उपयोग करें",
      "history.title": "आपका योगदान",
      "history.subtitle": "स्कैन में तस्वीरें नहीं, सिर्फ वस्तु और श्रेणी सहेजी जाती है।",
      "history.subtitleImages": "स्कैन की तस्वीरें Cloudinary में सहेजी जाती हैं; वस्तु और श्रेणी ऐप के डेटाबेस में रहती हैं।",
      "history.scans": "स्कैन",
      "history.points": "इको पॉइंट",
      "history.categories": "श्रेणियाँ",
      "history.refresh": "रीफ़्रेश",
      "nav.scan": "स्कैन",
      "nav.chat": "चैट",
      "nav.map": "नक्शा",
      "nav.history": "प्रभाव",
      "auth.login": "लॉग इन",
      "auth.signup": "खाता बनाएँ",
      "auth.logout": "लॉग आउट",
      "auth.email": "ईमेल",
      "auth.password": "पासवर्ड",
      "auth.name": "नाम",
      "auth.titleIn": "लॉग इन",
      "auth.titleUp": "खाता बनाएँ",
      "auth.blurb": "स्कैन अपने खाते में रखने के लिए लॉग इन करें। एडमिन खाता डैशबोर्ड भी खोलता है।",
      "auth.need": "नए हैं? खाता बनाएँ",
      "auth.have": "खाता है? लॉग इन करें",
      "auth.admin": "एडमिन",
      "auth.openAdmin": "एडमिन डैशबोर्ड खोलें",
      "auth.signedIn": "आप लॉग इन हैं।",
      "auth.guest": "लॉग इन से पहले स्कैन इसी डिवाइस पर रहते हैं।",
      "auth.accountLine": "{name} के रूप में लॉग इन",
      "auth.close": "बंद करें",
      "map.openArea": "यह इलाका Google Maps में खोलें",
      "map.showRoute": "रास्ता दिखाएँ",
      "map.openDir": "दिशा-निर्देश खोलें",

      greeting: "नमस्ते! किसी भी कचरे की वस्तु, डिब्बे का रंग, खाद या जमा करने की जगह के बारे में पूछें।",
      analysing: "आपकी फोटो देख रहे हैं…",
      errImage: "पहले कोई तस्वीर चुनें।",
      errGeneric: "कुछ गड़बड़ हुई। फिर से कोशिश करें।",
      errNetwork: "सर्वर से संपर्क नहीं हो रहा। क्या बैकएंड " + API + " पर चल रहा है?",
      errTimeout: "सर्वर ने बहुत देर ली। फिर से कोशिश करें।",
      errLarge: "तस्वीर बहुत बड़ी है। छोटी तस्वीर चुनें।",
      confidence: "विश्वास",
      uncertain: "कम विश्वास — नाम और नीचे दिए विकल्प जाँचें।",
      other: "अन्य संभावनाएँ",
      bin: "कहाँ डालें",
      steps: "क्या करें",
      avoid: "क्या न करें",
      rules: "नियम",
      findDropoff: "जमा करने की जगह खोजें",
      askAbout: "इस वस्तु के बारे में पूछें",
      scanAgain: "दूसरी वस्तु स्कैन करें",
      correct: "सही है",
      wrong: "गलत वस्तु",
      feedbackThanks: "धन्यवाद — इससे मॉडल बेहतर होगा।",
      chooseCorrect: "असल में कौन सी वस्तु थी?",
      submit: "भेजें",
      points: "+{n} इको पॉइंट",
      scanSaved: "स्कैन सहेजा गया।",
      chatThinking: "सोच रहे हैं…",
      chatError: "सहायक से संपर्क नहीं हो सका। नियम-कार्ड अभी भी काम करते हैं — स्कैन टैब आज़माएँ।",
      sources: "स्रोत",
      trace: "मैंने कैसे उत्तर दिया",
      chatFacilities: "बताई गई जगहें",
      nearby: "आसपास की जगहें",
      directions: "रास्ता",
      sampleData: "डेमो के लिए नमूना डेटा — लाइव OpenStreetMap के लिए FACILITY_PROVIDER=overpass सेट करें।",
      cached: "लाइव खोज नहीं हुई, इसलिए सहेजे गए नतीजे दिख रहे हैं।",
      live: "आपके पास की लाइव जगहें। नक्शा Google Maps है, रास्ता वहीं खुलता है।",
      noFacilities: "आसपास कोई संग्रह केंद्र नहीं मिला। दायरा बढ़ाएँ या नगर निगम हेल्पलाइन देखें।",
      locating: "आपकी लोकेशन खोज रहे हैं…",
      locationDenied: "आपकी लोकेशन उपलब्ध नहीं है। ब्राउज़र में लोकेशन की अनुमति दें और मैप फिर से खोलें। डेमो लोकेशन नहीं दिखाई जाएगी।",
      demoLocation: "डेमो क्षेत्र (मुंबई) दिख रहा है।",
      historyEmpty: "अभी कोई स्कैन नहीं। शुरू करने के लिए कुछ स्कैन करें।",
      loading: "लोड हो रहा है…",
      stepsNote: "निपटान के चरण अंग्रेज़ी में हैं; अनुवाद के लिए चैट टैब में पूछें।",
      barcode: "उत्पाद (बारकोड से)",
      packagingHint: "पैकेजिंग संकेत",
      attach: "फोटो जुड़ी है",
      remove: "हटाएँ",
      scanPointsAwarded: "आपने {n} इको पॉइंट कमाए।",
      of: "में से",
      topMatches: "शीर्ष मिलान",
      mapHint: "विवरण के लिए पिन दबाएँ।",
      helpline: "अगर कोई केंद्र न मिले, तो नगर निगम की कचरा हेल्पलाइन पर कॉल करें।",
      cat_ewaste: "ई-कचरा",
      cat_recyclable: "पुनर्चक्रण योग्य",
      cat_general: "सामान्य",
      cat_organic: "जैविक",
      cat_hazardous: "खतरनाक",
      cat_biomedical: "बायोमेडिकल"
    },
    mr: {
      "app.name": "कचरा मित्र",
      "app.tagline": "स्कॅन करा, वेगळे करा, योग्य ठिकाणी टाका.",
      "scan.title": "तुम्ही काय फेकत आहात?",
      "scan.subtitle": "फोटो घ्या किंवा अपलोड करा. आम्ही डबा, पद्धत आणि सुरक्षा इशारे सांगू.",
      "scan.camera": "फोटो घ्या",
      "scan.upload": "अपलोड",
      "scan.addDetails": "तपशील जोडा (ऐच्छिक, अचूकता वाढवते)",
      "scan.hintLabel": "तपशील",
      "scan.hintPlaceholder": "उदा. जुना नोकिया चार्जर, फुटलेली ट्यूबलाईट",
      "scan.barcodePlaceholder": "बारकोड (ऐच्छिक)",
      "scan.analyse": "वस्तू स्कॅन करा",
      "scan.point": "कचऱ्याच्या वस्तूवर कॅमेरा धरा",
      "scan.center": "एक वस्तू फ्रेममध्ये ठेवा — चांगला प्रकाश, स्वच्छ पार्श्वभूमी.",
      "scan.gallery": "गॅलरी",
      "scan.cameraShort": "कॅमेरा",
      "scan.ai": "एआय स्कॅन",
      "scan.scanning": "स्कॅन होत आहे…",
      "scan.more": "बारकोड",
      "scan.resultLabel": "स्कॅन निकाल",
      "scan.tap": "ओळखण्यासाठी शटर दाबा",
      "scan.dismiss": "निकाल लहान करा",
      "scan.waking": "सर्व्हर सुरू होत आहे…",
      "scan.woke": "सर्व्हर झोपलेला होता — {s} सेकंद लागले. पुढील स्कॅन वेगवान होतील.",
      "scan.compressed": "अपलोडसाठी फोटो लहान केला",
      "chat.title": "कचरा मित्राला विचारा",
      "chat.new": "नवीन चॅट",
      "chat.subtitle": "नियम, डबे, खत, ई-कचरा, बॅटरी — तुमच्या भाषेत.",
      "chat.chip1": "फुटलेली ट्यूबलाईट",
      "chat.chip2": "फ्लॅटमध्ये खत",
      "chat.chip3": "चिप्सचे पाकीट",
      "chat.chip4": "फुगलेली बॅटरी",
      "chat.q1": "फुटलेली ट्यूबलाईट कोणत्या डब्यात टाकावी?",
      "chat.q2": "मी फ्लॅटमध्ये घरी भाज्यांच्या सालींचे खत बनवू शकतो का?",
      "chat.q3": "चिप्सचे पाकीट रीसायकल होऊ शकते का?",
      "chat.q4": "फुगलेल्या फोन बॅटरीचे काय करावे?",
      "chat.placeholder": "वस्तू किंवा नियमाबद्दल विचारा…",
      "chat.send": "पाठवा",
      "chat.disclaimer": "हे सामान्य मार्गदर्शन आहे, कायदेशीर सल्ला नाही. स्थानिक नियम महानगरपालिकेकडून तपासा.",
      "map.title": "कुठे जमा करावे",
      "map.subtitle": "तुमच्या जवळचा लाइव्ह Google नकाशा. मार्ग Google Maps मध्ये उघडतो.",
      "map.category": "श्रेणी",
      "map.locate": "माझे स्थान वापरा",
      "history.title": "तुमचे योगदान",
      "history.subtitle": "स्कॅनमध्ये फोटो नाहीत — फक्त वस्तू आणि श्रेणी साठवली जाते.",
      "history.subtitleImages": "स्कॅनचे फोटो Cloudinary मध्ये साठवले जातात; वस्तू आणि श्रेणी ॲपच्या डेटाबेसमध्ये राहतात.",
      "history.scans": "स्कॅन",
      "history.points": "इको पॉइंट",
      "history.categories": "श्रेणी",
      "history.refresh": "रिफ्रेश",
      "nav.scan": "स्कॅन",
      "nav.chat": "चॅट",
      "nav.map": "नकाशा",
      "nav.history": "प्रभाव",
      "auth.login": "लॉग इन",
      "auth.signup": "खाते तयार करा",
      "auth.logout": "लॉग आउट",
      "auth.email": "ईमेल",
      "auth.password": "पासवर्ड",
      "auth.name": "नाव",
      "auth.titleIn": "लॉग इन",
      "auth.titleUp": "खाते तयार करा",
      "auth.blurb": "स्कॅन खात्यावर ठेवण्यासाठी लॉग इन करा. ॲडमिन खाते डॅशबोर्डही उघडते.",
      "auth.need": "नवीन आहात? खाते तयार करा",
      "auth.have": "खाते आहे? लॉग इन करा",
      "auth.admin": "ॲडमिन",
      "auth.openAdmin": "ॲडमिन डॅशबोर्ड उघडा",
      "auth.signedIn": "तुम्ही लॉग इन आहात.",
      "auth.guest": "लॉग इन करण्यापूर्वी स्कॅन या डिव्हाइसवर राहतात.",
      "auth.accountLine": "{name} म्हणून लॉग इन",
      "auth.close": "बंद करा",
      "map.openArea": "हा भाग Google Maps मध्ये उघडा",
      "map.showRoute": "मार्ग दाखवा",
      "map.openDir": "दिशा उघडा",

      greeting: "नमस्कार! कोणत्याही कचऱ्याच्या वस्तू, डब्याचा रंग, खत किंवा जमा करण्याच्या जागेबद्दल विचारा.",
      analysing: "तुमचा फोटो पाहत आहोत…",
      errImage: "आधी फोटो निवडा.",
      errGeneric: "काहीतरी चूक झाली. पुन्हा प्रयत्न करा.",
      errNetwork: "सर्व्हरशी संपर्क होत नाही. बॅकएंड " + API + " वर चालू आहे का?",
      errTimeout: "सर्व्हरने खूप वेळ घेतला. पुन्हा प्रयत्न करा.",
      errLarge: "फोटो खूप मोठा आहे. लहान फोटो निवडा.",
      confidence: "विश्वास",
      uncertain: "कमी विश्वास — नाव आणि खालील पर्याय तपासा.",
      other: "इतर शक्यता",
      bin: "कुठे टाकावे",
      steps: "काय करावे",
      avoid: "काय करू नका",
      rules: "नियम",
      findDropoff: "जमा करण्याची जागा शोधा",
      askAbout: "या वस्तूबद्दल विचारा",
      scanAgain: "दुसरी वस्तू स्कॅन करा",
      correct: "बरोबर",
      wrong: "चुकीची वस्तू",
      feedbackThanks: "धन्यवाद — यामुळे मॉडेल सुधारेल.",
      chooseCorrect: "खरं तर कोणती वस्तू होती?",
      submit: "पाठवा",
      points: "+{n} इको पॉइंट",
      scanSaved: "स्कॅन साठवला.",
      chatThinking: "विचार करत आहोत…",
      chatError: "सहाय्यकाशी संपर्क होऊ शकला नाही. नियम-कार्ड अजूनही चालतात — स्कॅन टॅब वापरा.",
      sources: "स्रोत",
      trace: "मी कसे उत्तर दिले",
      chatFacilities: "सांगितलेली ठिकाणे",
      nearby: "जवळील ठिकाणे",
      directions: "मार्ग",
      sampleData: "डेमोसाठी नमुना डेटा — थेट OpenStreetMap साठी FACILITY_PROVIDER=overpass सेट करा.",
      cached: "थेट शोध झाला नाही, म्हणून साठवलेले निकाल दिसत आहेत.",
      live: "तुमच्या जवळची थेट ठिकाणे. नकाशा Google Maps आहे, मार्ग तिथे उघडतो.",
      noFacilities: "जवळ कोणतेही संकलन केंद्र सापडले नाही. परिसर वाढवा किंवा महानगरपालिका हेल्पलाइन पहा.",
      locating: "तुमचे स्थान शोधत आहोत…",
      locationDenied: "तुमचे स्थान उपलब्ध नाही. ब्राउझरमध्ये स्थानाची परवानगी द्या आणि नकाशा पुन्हा उघडा. डेमो ठिकाणे दाखवली जाणार नाहीत.",
      demoLocation: "डेमो भाग (मुंबई) दाखवत आहोत.",
      historyEmpty: "अजून स्कॅन नाही. सुरुवात करण्यासाठी काहीतरी स्कॅन करा.",
      loading: "लोड होत आहे…",
      stepsNote: "विल्हेवाटीचे टप्पे इंग्रजीत आहेत; भाषांतरासाठी चॅट टॅबमध्ये विचारा.",
      barcode: "उत्पादन (बारकोडवरून)",
      packagingHint: "पॅकेजिंग संकेत",
      attach: "फोटो जोडला",
      remove: "काढा",
      scanPointsAwarded: "तुम्ही {n} इको पॉइंट मिळवले.",
      of: "पैकी",
      topMatches: "शीर्ष जुळणी",
      mapHint: "तपशीलासाठी पिन दाबा.",
      helpline: "केंद्र सापडले नाही तर महानगरपालिकेच्या कचरा हेल्पलाइनवर कॉल करा.",
      cat_ewaste: "ई-कचरा",
      cat_recyclable: "पुनर्वापरयोग्य",
      cat_general: "सामान्य",
      cat_organic: "सेंद्रिय",
      cat_hazardous: "धोकादायक",
      cat_biomedical: "बायोमेडिकल"
    }
  };

  const CAT_EMOJI = {
    ewaste: "🔌", recyclable: "♻️", general: "🗑️",
    organic: "🌱", hazardous: "⚠️", biomedical: "🩺"
  };

  // ---------------------------------------------------------------- state
  const state = {
    lang: localStorage.getItem("waste.lang") || "en",
    file: null,
    uploadPromise: null,
    result: null,
    chatFile: null,
    deviceId: getDeviceId(),
    sessionId: localStorage.getItem("waste.session") || null,
    chatContext: null,
    geo: null,
    map: null,
    markers: [],
    youMarker: null,
    mapLoaded: false,
    historyLoaded: false,
    taxonomy: null,
    messages: [],
    chatBusy: false,
    auth: null,
    authMode: "in",
    selectedFacility: null,
    cameraStream: null
  };
  if (!STR[state.lang]) state.lang = "en";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function t(key, vars) {
    let s = (STR[state.lang] && STR[state.lang][key]) || STR.en[key] || key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll("{" + k + "}", v);
    return s;
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function mdLite(text) {
    const escaped = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?]|$)/g, "$1<em>$2</em>");
    return escaped.split(/\n{2,}/).map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-•]\s+/.test(l))) {
        return "<ul>" + lines.map((l) => "<li>" + l.replace(/^\s*[-•]\s+/, "") + "</li>").join("") + "</ul>";
      }
      if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        return "<ol>" + lines.map((l) => "<li>" + l.replace(/^\s*\d+[.)]\s+/, "") + "</li>").join("") + "</ol>";
      }
      return "<p>" + lines.join("<br>") + "</p>";
    }).join("");
  }

  function getDeviceId() {
    let id = localStorage.getItem("waste.device");
    if (!id) {
      id = "dev_" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 18)
        : Math.random().toString(36).slice(2) + Date.now().toString(36));
      localStorage.setItem("waste.device", id);
    }
    return id;
  }

  function toast(msg, ms = 3200) {
    const box = $("#toast");
    box.textContent = msg;
    box.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => box.classList.add("hidden"), ms);
  }

  // Free-tier hosts sleep after 15 minutes of inactivity and then need ~50 s to answer
  // the first request. Poke them now, while the user is still framing the shot.
  function wakeServer() {
    fetch(API + "/health", { cache: "no-store" }).catch(() => { /* offline is fine */ });
  }

  async function api(path, options = {}, timeoutMs = 30000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const headers = new Headers(options.headers || {});
    if (state.deviceId) headers.set("X-Device-Id", state.deviceId);
    if (state.auth?.token) headers.set("Authorization", "Bearer " + state.auth.token);
    try {
      const res = await fetch(API + path, { ...options, headers, signal: controller.signal });
      if (res.status === 401 && path.startsWith("/auth/me")) {
        clearAuth();
      }
      if (!res.ok) {
        let detail = "";
        try {
          const body = await res.json();
          detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
        } catch { /* not json */ }
        throw new Error(detail || ("HTTP " + res.status));
      }
      return await res.json();
    } catch (err) {
      if (err.name === "AbortError") throw new Error(t("errTimeout"));
      if (err instanceof TypeError) throw new Error(t("errNetwork"));
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------------------------------------------------------------- auth
  function setAuth(token, user) {
    state.auth = { token, user };
    localStorage.setItem("waste.auth", JSON.stringify({ token, user }));
    refreshAuthUI();
  }

  function clearAuth() {
    state.auth = null;
    localStorage.removeItem("waste.auth");
    refreshAuthUI();
  }

  async function restoreAuth() {
    try {
      const neon = await window.neonAuthReady;
      if (neon?.error) throw new Error(neon.error);
      if (!neon) throw new Error("Neon Auth client did not initialize");
      const authState = await neon.getSession();
      if (!authState.token || !authState.session) {
        clearAuth();
        return;
      }
      state.auth = { token: authState.token, user: authState.session.user || authState.session.data?.user || null };
      const me = await api("/auth/me", {}, 10000);
      state.auth.user = me.user;
      localStorage.setItem("waste.auth", JSON.stringify(state.auth));
      refreshAuthUI();
    } catch (err) {
      console.warn("Neon Auth session restore:", err.message);
      clearAuth();
    }
  }

  function refreshAuthUI() {
    const signedIn = !!state.auth;
    const btn = $("#account-btn");
    if (btn) {
      btn.textContent = signedIn ? t("auth.logout") : t("auth.login");
      btn.dataset.i18n = signedIn ? "auth.logout" : "auth.login";
    }
    const adminLink = $("#auth-admin");
    if (adminLink) adminLink.classList.toggle("hidden", !(signedIn && state.auth.user && state.auth.user.is_admin));
    renderAccount();
  }

  function renderAccount() {
    const line = $("#account-line");
    if (line) line.textContent = state.auth ? signedInText() : t("auth.guest");
    const jump = $("#admin-jump");
    const isAdmin = !!(state.auth && state.auth.user && state.auth.user.is_admin);
    if (jump) jump.classList.toggle("hidden", !isAdmin);
  }

  function openAuth() {
    $("#auth-dialog").classList.remove("hidden");
    $("#auth-dialog").setAttribute("aria-hidden", "false");
    $("#auth-error").classList.add("hidden");
  }

  function closeAuth() {
    $("#auth-dialog").classList.add("hidden");
    $("#auth-dialog").setAttribute("aria-hidden", "true");
  }

  function toggleAuthMode() {
    state.authMode = state.authMode === "in" ? "up" : "in";
    const nameBox = $("#auth-name");
    const nameLabel = $("#auth-name-label");
    const submit = $("#auth-submit");
    const switchBtn = $("#auth-switch");
    const title = $("#auth-title");
    const isUp = state.authMode === "up";
    if (nameBox) nameBox.style.display = isUp ? "" : "none";
    if (nameLabel) nameLabel.style.display = isUp ? "" : "none";
    if (submit) submit.textContent = t(isUp ? "auth.signup" : "auth.login");
    if (switchBtn) switchBtn.textContent = t(isUp ? "auth.have" : "auth.need");
    if (title) title.textContent = t(isUp ? "auth.titleUp" : "auth.titleIn");
    $("#auth-error").classList.add("hidden");
  }

  async function submitAuth(event) {
    event.preventDefault();
    const btn = $("#auth-submit");
    const error = $("#auth-error");
    const email = $("#auth-email").value.trim();
    const password = $("#auth-password").value;
    const name = $("#auth-name").value.trim();
    btn.disabled = true;
    error.classList.add("hidden");
    try {
      const neon = await window.neonAuthReady;
      if (neon?.error) throw new Error(neon.error);
      if (!neon) throw new Error("Neon Auth is unavailable. Refresh and try again.");
      const result = state.authMode === "up"
        ? await neon.signUp({ email, password, name })
        : await neon.signIn({ email, password });
      if (!result.token) {
        throw new Error("Authentication completed but no session token was returned. If email verification is enabled, verify your email and sign in again.");
      }
      const me = await fetch(API + "/auth/me", {
        headers: { "Authorization": "Bearer " + result.token, "X-Device-Id": state.deviceId },
        cache: "no-store"
      });
      const body = await me.json().catch(() => ({}));
      if (!me.ok) throw new Error(body.detail || "Could not create your application profile.");
      setAuth(result.token, body.user);
      closeAuth();
      toast(signedInText());
    } catch (err) {
      error.textContent = err.message || t("errGeneric");
      error.classList.remove("hidden");
    } finally {
      btn.disabled = false;
    }
  }

  function signedInText() {
    return state.auth && state.auth.user
      ? t("auth.accountLine", { name: state.auth.user.name || state.auth.user.email })
      : t("auth.signedIn");
  }

  async function handleAuthClick() {
    if (state.auth) {
      try {
        const neon = await window.neonAuthReady;
        if (neon && !neon.error) await neon.signOut();
      } catch (err) {
        console.warn("Neon Auth sign-out:", err);
      }
      clearAuth();
      toast(t("auth.logout"));
      return;
    }
    openAuth();
  }

  // ---------------------------------------------------------------- i18n apply
  function applyI18n() {
    document.documentElement.lang = state.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    renderAccount();
    $$(".lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
    $("#chat-input").placeholder = t("chat.placeholder");
    if (state.result) renderResult(state.result);
    if (state.historyLoaded) loadHistory(true);
  }

  function setLang(lang) {
    if (!STR[lang]) return;
    state.lang = lang;
    localStorage.setItem("waste.lang", lang);
    applyI18n();
    retitleMapNote();
    if (state.result || state.historyLoaded) {
      ensureTaxonomy().then(() => {
        if (state.result) renderResult(state.result);
        if (state.historyLoaded) loadHistory(true);
      });
    }
  }

  // ---------------------------------------------------------------- tabs
  function showTab(name, { updateHash = true } = {}) {
    $$(".tab").forEach((el) => el.classList.toggle("active", el.id === "tab-" + name));
    $$(".navbtn").forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (updateHash) history.replaceState(null, "", "#" + name);
    if (name === "map") {
      setTimeout(() => { if (!state.mapLoaded) locateAndLoad(); }, 60);
    }
    if (name === "history") loadHistory();
    window.scrollTo(0, 0);
    if (name === "chat") setTimeout(() => $("#chat-input").focus({ preventScroll: true }), 80);
  }

  // ---------------------------------------------------------------- scan
  // Phone cameras produce 3-8 MB files. Uploading that over mobile data is the single
  // biggest source of "the scan is slow", and the model only ever sees 1024 px anyway
  // (the server downscales). So shrink in the browser first: ~200 KB instead of ~5 MB.
  async function compressImage(file, maxSide = 1280, quality = 0.85) {
    const original = { blob: file, name: file.name || "scan.jpg" };
    try {
      if (!window.createImageBitmap) return original;
      const bitmap = await createImageBitmap(file);
      const longSide = Math.max(bitmap.width, bitmap.height);
      const scale = Math.min(1, maxSide / longSide);
      // Already small enough: re-encoding would only lose quality.
      if (scale >= 0.99 && file.size < 700 * 1024) { bitmap.close?.(); return original; }

      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close?.();

      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (!blob || blob.size >= file.size) return original;
      return { blob, name: "scan.jpg" };
    } catch {
      return original; // HEIC and friends: let the server have the original bytes
    }
  }

// ========================================
// KACHRA MITRA - DESKTOP WEBCAM
// ========================================

function stopWebcam() {
    if (state.cameraStream) {
        state.cameraStream.getTracks().forEach(track => track.stop());
        state.cameraStream = null;
    }

    const video = $("#webcam-preview");

    if (video) {
        video.srcObject = null;
    }

    $("#webcam-wrap")?.classList.add("hidden");
    $("#lens-stage")?.classList.remove("camera-active");
}

async function openWebcam() {
    if (!navigator.mediaDevices?.getUserMedia) {
        toast("Camera is unavailable. Please use Gallery instead.");
        return;
    }

    try {
        stopWebcam();

      
const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
    || (navigator.maxTouchPoints > 1 && /Macintosh/i.test(navigator.userAgent));

const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
        facingMode: {
            ideal: isMobile ? "environment" : "user"
        },
        width: { ideal: 1280 },
        height: { ideal: 720 }
    }
});


        state.cameraStream = stream;

        const video = $("#webcam-preview");
        video.srcObject = stream;

        $("#webcam-wrap").classList.remove("hidden");
        $("#lens-stage").classList.add("camera-active");

        await video.play();

    } catch (error) {
        console.error("Webcam error:", error);

        if (error.name === "NotAllowedError") {
            toast("Please allow camera permission in your browser.");
        } else if (error.name === "NotFoundError") {
            toast("No webcam found on this device.");
        } else if (error.name === "NotReadableError") {
            toast("Camera is being used by another application.");
        } else {
            toast("Unable to open webcam. Check camera permissions.");
        }
    }
}

async function captureWebcamPhoto() {
    const video = $("#webcam-preview");

    if (!state.cameraStream || !video.videoWidth) {
        toast("Camera is not ready. Please wait.");
        return;
    }

    const canvas = document.createElement("canvas");

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const context = canvas.getContext("2d");

    context.drawImage(
        video,
        0,
        0,
        canvas.width,
        canvas.height
    );

    const blob = await new Promise(resolve =>
        canvas.toBlob(resolve, "image/jpeg", 0.9)
    );

    if (!blob) {
        toast("Photo capture failed.");
        return;
    }

    const photo = new File(
        [blob],
        "kachra-webcam-" + Date.now() + ".jpg",
        { type: "image/jpeg" }
    );

    stopWebcam();
    setFile(photo);
}

  function setFile(file) {
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast(t("errImage")); return; }
    if (file.size > 8 * 1024 * 1024) { toast(t("errLarge")); return; }
    state.file = file;
    state.uploadPromise = compressImage(file);
    const url = URL.createObjectURL(file);
    const img = $("#preview");
    img.src = url;
    img.onload = () => URL.revokeObjectURL(url);
    $("#preview-wrap").classList.remove("hidden");
    $("#lens-empty").classList.add("hidden");
    $("#lens-stage").classList.add("has-image");
    $("#clear-photo").classList.remove("hidden");
    $("#classify-btn").disabled = false;
    $("#scan-go").disabled = false;
    $("#scan-error").classList.add("hidden");
  }

  function clearPhoto() {
    stopWebcam();
    
    state.file = null;
    state.uploadPromise = null;
    $("#preview").removeAttribute("src");
    $("#preview-wrap").classList.add("hidden");
    $("#lens-empty").classList.remove("hidden");
    $("#lens-stage").classList.remove("has-image", "scanning");
    $("#clear-photo").classList.add("hidden");
    $("#camera").value = "";
    $("#upload").value = "";
    $("#classify-btn").disabled = true;
    $("#scan-go").disabled = true;
    $("#result").classList.add("hidden");
    $("#scan-error").classList.add("hidden");
  }

  async function classify() {
    if (!state.file) { toast(t("errImage")); return; }
    const btn = $("#classify-btn");
    const label = $("#classify-label");
    const errBox = $("#scan-error");
    const stage = $("#lens-stage");
    errBox.classList.add("hidden");
    btn.disabled = true;
    $("#scan-go").disabled = true;
    stage.classList.add("scanning");
    label.textContent = t("analysing");

    const startedAt = performance.now();
    // A sleeping free-tier server takes ~50 s to answer. Say so instead of looking frozen.
    const slowTimer = setTimeout(() => { label.textContent = t("scan.waking"); }, 4000);

    const body = new FormData();
    const packed = await (state.uploadPromise || compressImage(state.file));
    body.append("file", packed.blob, packed.name);
    body.append("lang", state.lang);
    body.append("device_id", state.deviceId);
    const hint = $("#text-hint").value.trim();
    const barcode = $("#barcode").value.trim();
    if (hint) body.append("text_hint", hint);
    if (barcode) body.append("barcode", barcode);

    try {
      // 90 s, not 40: a cold Render start plus a 3 MB upload legitimately fits in that,
      // while a genuinely dead server still fails before the user gives up.
      const r = await api("/classify", { method: "POST", body }, 90000);
      state.result = r;
      state.chatContext = null;
      renderResult(r);
      const secs = Math.round((performance.now() - startedAt) / 1000);
      if (secs >= 5) {
        toast(t("scan.woke", { s: secs }), 6000);
      } else if (r.eco_points > 0) {
        toast(t("scanPointsAwarded", { n: r.eco_points }));
      }
      state.historyLoaded = false;
      if (window.innerWidth < 980) {
        setTimeout(() => $("#result").scrollIntoView({ behavior: "smooth", block: "start" }), 140);
      }
    } catch (err) {
      errBox.textContent = err.message || t("errGeneric");
      errBox.classList.remove("hidden");
    } finally {
      clearTimeout(slowTimer);
      stage.classList.remove("scanning");
      btn.disabled = !state.file;
      $("#scan-go").disabled = !state.file;
      label.textContent = t("scan.analyse");
    }
  }

  function renderResult(r) {
    const host = $("#result");
    const cat = r.category || "general";
    const pct = Math.round((r.confidence || 0) * 100);
    const catLabel = t("cat_" + cat) || r.category_display || cat;
    const itemLabel = taxName(r.item) || r.item_display || r.item;
    const warnings = (r.warnings || []).map((w) => `
      <div class="warning ${escapeHtml(w.level)}">
        <span class="wi" aria-hidden="true">${w.level === "danger" ? "⛔" : w.level === "caution" ? "⚠️" : "ℹ️"}</span>
        <span>${escapeHtml(w.text)}</span>
      </div>`).join("");

    const steps = (r.disposal?.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    const dont = (r.disposal?.do_not || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    const rules = (r.disposal?.rule_refs || []).map((s) => `<span class="rule-chip">${escapeHtml(s)}</span>`).join("");
    const alternatives = r.uncertain && r.top_k?.length > 1
      ? `<div class="alt-row"><span class="muted small">${escapeHtml(t("other"))}:</span>` +
        r.top_k.slice(1).map((x) => `<button type="button" class="alt-chip"
          data-alt="${escapeHtml(x.item)}" data-alt-name="${escapeHtml(x.name)}">${escapeHtml(x.name)}</button>`).join("") +
        `</div>`
      : "";

    const barcode = r.barcode_hint ? `
      <div class="followup" style="background:#eff8ff;border-color:#b2ddff">
        <strong>${escapeHtml(t("barcode"))}</strong><br>
        ${escapeHtml([r.barcode_hint.name, r.barcode_hint.brand].filter(Boolean).join(" · ") || r.barcode_hint.code)}<br>
        <span class="muted small">${escapeHtml(t("packagingHint"))}: ${escapeHtml(r.barcode_hint.recyclable_hint || "unknown")}
        ${r.barcode_hint.packaging?.length ? " · " + escapeHtml(r.barcode_hint.packaging.slice(0, 3).join(", ")) : ""}</span>
      </div>` : "";

    const noteEn = state.lang !== "en" ? `<p class="muted tiny">${escapeHtml(t("stepsNote"))}</p>` : "";

    host.innerHTML = `
      <button class="sheet-handle" data-act="toggle" aria-expanded="true" aria-label="${escapeHtml(t("scan.dismiss"))}">
        <span></span>
      </button>
      <div class="sheet-top">
        <span class="sheet-kicker">${escapeHtml(t("scan.resultLabel"))}</span>
        <span class="badge ${escapeHtml(cat)}">${escapeHtml(catLabel)}</span>
      </div>

      <div class="sheet-hero">
        <div class="result-icon ${escapeHtml(cat)}" aria-hidden="true">${CAT_EMOJI[cat] || "♻️"}</div>
        <div class="result-head">
          <h2 class="result-item">${escapeHtml(itemLabel)}</h2>
          <p class="result-cat">${escapeHtml(catLabel)}</p>
        </div>
        <div class="conf-ring ${pct < 60 ? "low" : ""}" style="--pct:${Math.max(0, Math.min(100, pct))}"
             title="${escapeHtml(t("confidence"))}: ${pct}%">
          <span>${pct}<small>%</small></span>
        </div>
      </div>

      <div class="sheet-body">
        ${r.uncertain ? `<div class="followup">${escapeHtml(t("uncertain"))}${r.follow_up ? " " + escapeHtml(r.follow_up) : ""}</div>` : ""}
        ${alternatives}
        ${barcode}
        ${warnings ? `<div class="warnings">${warnings}</div>` : ""}

        <div class="bin-card ${escapeHtml(cat)}">
          <span class="bin-emoji" aria-hidden="true">🪣</span>
          <div>
            <small>${escapeHtml(t("bin"))}</small>
            <strong>${escapeHtml(r.disposal?.bin || catLabel)}</strong>
          </div>
        </div>

        ${steps ? `<h3 class="sheet-label">${escapeHtml(t("steps"))}</h3><ol class="steps">${steps}</ol>` : ""}
        ${dont ? `<h3 class="sheet-label avoid">${escapeHtml(t("avoid"))}</h3><ul class="donot">${dont}</ul>` : ""}
        ${rules ? `<div class="rules">${rules}</div>` : ""}
        ${noteEn}

        <div class="result-actions">
          <button class="btn primary" data-act="map">📍 ${escapeHtml(t("findDropoff"))}</button>
          <button class="btn ghost" data-act="ask">💬 ${escapeHtml(t("askAbout"))}</button>
          <button class="btn ghost" data-act="again">📷 ${escapeHtml(t("scanAgain"))}</button>
        </div>

        <div class="feedback-row">
          <span>${escapeHtml(t("correct"))}?</span>
          <button class="btn tiny ghost" data-act="fb-ok">👍 ${escapeHtml(t("correct"))}</button>
          <button class="btn tiny ghost" data-act="fb-wrong">👎 ${escapeHtml(t("wrong"))}</button>
          <div id="fb-picker" class="hidden" style="flex:1 1 100%"></div>
        </div>
      </div>`;

    host.classList.remove("hidden", "collapsed");
    host.querySelector('[data-act="toggle"]').addEventListener("click", (e) => {
      const collapsed = host.classList.toggle("collapsed");
      e.currentTarget.setAttribute("aria-expanded", String(!collapsed));
    });

    host.querySelector('[data-act="map"]').addEventListener("click", () => openMapFor(cat));
    host.querySelector('[data-act="ask"]').addEventListener("click", () => {
      state.chatContext = { scan_id: r.scan_id, item: r.item, category: r.category, confidence: r.confidence };
      showTab("chat");
      const input = $("#chat-input");
      input.value = state.lang === "hi" ? `इस वस्तु का सही निपटान कैसे करें?` :
        state.lang === "mr" ? `या वस्तूची योग्य विल्हेवाट कशी करावी?` :
        `How should I dispose of ${r.item_display || r.item} properly?`;
      autoGrow(input);
      input.focus();
    });
    host.querySelector('[data-act="again"]').addEventListener("click", () => {
      clearPhoto();
      $("#result").classList.add("hidden");
      $("#text-hint").value = "";
      $("#barcode").value = "";
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    host.querySelector('[data-act="fb-ok"]').addEventListener("click", () => sendFeedback(r, null));
    host.querySelector('[data-act="fb-wrong"]').addEventListener("click", () => showFeedbackPicker(r));

    // One tap on "it was actually X": log the correction and re-scan with that name as the
    // hint, so the server answers with X's bin and steps instead of just a guess.
    host.querySelectorAll("[data-alt]").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("#text-hint").value = btn.dataset.altName || btn.dataset.alt;
        sendFeedback(r, btn.dataset.alt);
        classify();
      });
    });
  }

  async function sendFeedback(r, correctItem) {
    const cat = correctItem ? itemCategory(correctItem) : null;
    try {
      await api("/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scan_id: r.scan_id,
          correct_item: correctItem || r.item,
          correct_category: cat || r.category,
          comment: correctItem ? "frontend correction" : null
        })
      }, 12000);
      toast(t("feedbackThanks"));
      const picker = $("#fb-picker");
      if (picker) { picker.classList.add("hidden"); picker.innerHTML = ""; }
    } catch (err) {
      toast(err.message || t("errGeneric"));
    }
  }

  function itemCategory(id) {
    if (!state.taxonomy) return null;
    for (const c of state.taxonomy) {
      if ((c.items || []).some((i) => i.id === id)) return c.id;
    }
    return null;
  }

  function taxName(id) {
    if (!state.taxonomy) return null;
    for (const c of state.taxonomy) {
      const hit = (c.items || []).find((i) => i.id === id);
      if (hit) return hit[state.lang] || hit.en || null;
    }
    return null;
  }

  async function showFeedbackPicker(r) {
    await ensureTaxonomy();
    const picker = $("#fb-picker");
    if (!picker) return;
    const options = state.taxonomy.map((c) => {
      const items = (c.items || []).map((i) =>
        `<option value="${escapeHtml(i.id)}">${escapeHtml(i[state.lang] || i.en || i.id)}</option>`).join("");
      return `<optgroup label="${escapeHtml(t("cat_" + c.id))}">${items}</optgroup>`;
    }).join("");
    picker.innerHTML = `
      <label class="sr-only" for="fb-item">${escapeHtml(t("chooseCorrect"))}</label>
      <div style="display:flex;gap:.4rem;margin-top:.5rem">
        <select id="fb-item">${options}</select>
        <button class="btn tiny primary" id="fb-submit">${escapeHtml(t("submit"))}</button>
      </div>`;
    picker.classList.remove("hidden");
    $("#fb-submit").addEventListener("click", () => {
      const val = $("#fb-item").value;
      if (val) sendFeedback(r, val);
    });
  }

  // ---------------------------------------------------------------- chat
  function addMessage(kind, html, extraClass = "") {
    const div = document.createElement("div");
    div.className = "msg " + kind + (extraClass ? " " + extraClass : "");
    div.innerHTML = html;
    $("#messages").appendChild(div);
    $("#messages").scrollTop = $("#messages").scrollHeight;
    return div;
  }

  function renderGreeting() {
    $("#messages").innerHTML = "";
    addMessage("bot", `<p>${escapeHtml(t("greeting"))}</p>`);
    state.messages = [];
  }

  function chatContextForRequest() {
    let ctx = state.chatContext;
    if (!ctx && state.result) {
      ctx = {
        scan_id: state.result.scan_id, item: state.result.item,
        category: state.result.category, confidence: state.result.confidence
      };
    }
    ctx = ctx ? { ...ctx } : {};
    if (state.geo) { ctx.lat = state.geo.lat; ctx.lng = state.geo.lng; }
    return Object.keys(ctx).length ? ctx : null;
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.onerror = () => reject(new Error("read failed"));
      reader.readAsDataURL(file);
    });
  }

  async function sendChat() {
    if (state.chatBusy) return;
    const input = $("#chat-input");
    const text = input.value.trim();
    const photo = state.chatFile;
    if (!text && !photo) return;

    state.chatBusy = true;
    input.value = "";
    autoGrow(input);
    addMessage("user", `${photo ? "📷 " + escapeHtml(t("attach")) + "<br>" : ""}${escapeHtml(text || "")}`);
    state.messages.push({ role: "user", text });

    const typing = addMessage("bot typing", escapeHtml(t("chatThinking")));

    let image_base64 = null;
    if (photo) {
      try { image_base64 = await fileToBase64(photo); }
      catch { toast(t("errGeneric")); }
    }
    state.chatFile = null;
    $("#chat-attach-preview")?.remove();
    $("#chat-photo").value = "";

    const payload = {
      message: text || (image_base64 ? "What is this item and how should I dispose of it?" : ""),
      lang: state.lang,
      context: chatContextForRequest()
    };
    if (image_base64) payload.image_base64 = image_base64;
    if (state.sessionId) payload.session_id = state.sessionId;

    try {
      const r = await api("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }, 45000);

      state.sessionId = r.session_id;
      localStorage.setItem("waste.session", r.session_id);
      typing.remove();

      let html = mdLite(r.answer || "");
      for (const w of r.warnings || []) {
        html += `<span class="msg-warn">${w.level === "danger" ? "⛔ " : "⚠️ "}${escapeHtml(w.text)}</span>`;
      }
      if (r.facilities?.length) {
        html += `<span class="meta"><strong>${escapeHtml(t("chatFacilities"))}</strong></span>`;
        html += r.facilities.map((f) => `
          <div class="facility" style="margin:.4rem 0">
            <div><h3>${escapeHtml(f.name)}</h3>
              <p>${escapeHtml(f.address || "")}${f.distance_m ? " · " + Math.round(f.distance_m) + " m" : ""}</p>
              <a href="${googleDir(f.lat, f.lng)}" target="_blank" rel="noopener">${escapeHtml(t("map.openDir"))}</a>
            </div>
          </div>`).join("");
      }
      if (r.sources?.length) {
        const links = r.sources.map((s) => s.url
          ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title)}</a>`
          : escapeHtml(s.title)).join(" · ");
        html += `<span class="meta">${escapeHtml(t("sources"))}: ${links}</span>`;
      }
      if (r.tool_trace?.length) {
        html += `<details class="meta"><summary>${escapeHtml(t("trace"))}</summary><span>${escapeHtml(r.tool_trace.join(" → "))}</span></details>`;
      }
      addMessage("bot", html);
      state.messages.push({ role: "assistant", text: r.answer });

      if (r.facilities?.length) {
        state.lastFacilities = r.facilities;
        state.mapLoaded = false;
      }
    } catch (err) {
      typing.remove();
      addMessage("bot", `<p>${escapeHtml(t("chatError"))}</p><span class="meta">${escapeHtml(err.message || "")}</span>`);
    } finally {
      state.chatBusy = false;
    }
  }

  function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  function newChat() {
    if (state.sessionId) {
      fetch(API + "/chat/reset?session_id=" + encodeURIComponent(state.sessionId), { method: "POST" }).catch(() => {});
    }
    state.sessionId = null;
    localStorage.removeItem("waste.session");
    state.chatContext = null;
    state.chatFile = null;
    $("#chat-attach-preview")?.remove();
    renderGreeting();
    $("#chat-input").focus();
  }

  // ---------------------------------------------------------------- map
  const MAP_QUERY = {
    ewaste: "e-waste recycling center",
    recyclable: "recycling center",
    organic: "compost drop-off",
    hazardous: "hazardous waste drop-off",
    biomedical: "biomedical waste collection",
    general: "waste collection center"
  };

  function mapQuery() {
    return MAP_QUERY[$("#map-category")?.value] || "recycling center";
  }

  function googleDir(lat, lng) {
    let url = "https://www.google.com/maps/dir/?api=1&destination=" + lat + "," + lng + "&travelmode=driving";
    if (state.geo) url += "&origin=" + state.geo.lat + "," + state.geo.lng;
    return url;
  }

  function googleAreaUrl(lat, lng) {
    return "https://www.google.com/maps/search/" + encodeURIComponent(mapQuery()) + "/@" + lat + "," + lng + ",14z";
  }

  function googleEmbedArea(lat, lng) {
    const q = encodeURIComponent(mapQuery() + " near " + lat + "," + lng);
    return "https://maps.google.com/maps?q=" + q + "&z=14&output=embed";
  }

  function googleEmbedRoute(lat, lng) {
    if (!state.geo) return "https://maps.google.com/maps?q=" + lat + "," + lng + "&z=16&output=embed";
    return "https://maps.google.com/maps?saddr=" + state.geo.lat + "," + state.geo.lng
      + "&daddr=" + lat + "," + lng + "&output=embed";
  }

  function setMapFrame(src) {
    const frame = $("#gmap");
    if (frame) frame.src = src;
  }

  function currentMapPoint() {
    if (state.geo) return [state.geo.lat, state.geo.lng];
    return DEFAULT_CENTER;
  }

  function mapNote(text, kind = "note") {
    const box = $("#map-note");
    box.textContent = text || "";
    box.className = text ? (kind === "muted" ? "note" : "note") : "note hidden";
    if (!text) box.classList.add("hidden");
    box.dataset.text = text || "";
  }

  function retitleMapNote() {
    const box = $("#map-note");
    if (box && box.dataset.text) box.textContent = box.dataset.text;
  }

  async function locateAndLoad() {
    const list = $("#facility-list");
    state.geo = null;
    if (!navigator.geolocation) {
      mapNote(t("locationDenied"));
      list.innerHTML = `<div class="card"><p class="muted">${escapeHtml(t("locationDenied"))}</p></div>`;
      return;
    }
    mapNote(t("locating"));
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        state.geo = { lat: pos.coords.latitude, lng: pos.coords.longitude, acc: pos.coords.accuracy };
        setMapFrame(googleEmbedArea(state.geo.lat, state.geo.lng));
        await loadFacilities(state.geo.lat, state.geo.lng);
      },
      () => {
        // Never query Mumbai or show fixed demo coordinates when location is denied.
        state.geo = null;
        mapNote(t("locationDenied"));
        list.innerHTML = `<div class="card"><p class="muted">${escapeHtml(t("locationDenied"))}</p></div>`;
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 15000 }
    );
  }

  async function loadFacilities(lat, lng) {
    const cat = $("#map-category").value;
    const list = $("#facility-list");
    list.innerHTML = `<p class="muted small">${escapeHtml(t("loading"))}</p>`;
    try {
      const q = new URLSearchParams({ lat: String(lat), lng: String(lng), category: cat, radius_m: "8000", limit: "20" });
      const r = await api("/facilities?" + q.toString(), {}, 30000);

      if (r.source === "fixture") mapNote(r.note || t("sampleData"));
      else if (r.stale) mapNote(t("cached"));
      else mapNote(r.note || t("live"), "muted");

      setMapFrame(googleEmbedArea(lat, lng));
      state.selectedFacility = null;

      if (!r.results?.length) {
        mapNote(t("noFacilities"));
        list.innerHTML = `<div class="card"><p class="muted">${escapeHtml(t("noFacilities"))}</p>
          <p class="muted small">${escapeHtml(t("helpline"))}</p>
          <a class="btn small primary" href="${googleAreaUrl(lat, lng)}" target="_blank" rel="noopener">${escapeHtml(t("map.openArea"))}</a></div>`;
        state.mapLoaded = true;
        return;
      }

      state.facilities = r.results;
      list.innerHTML = r.results.map((f, i) => `
        <div class="facility" data-idx="${i}">
          <div>
            <h3>${escapeHtml(f.name)}</h3>
            <p>${escapeHtml(f.address || "")}</p>
            ${f.hours ? `<p>🕒 ${escapeHtml(f.hours)}</p>` : ""}
            <div class="facility-actions">
              <button type="button" class="btn tiny ghost" data-act="route">${escapeHtml(t("map.showRoute"))}</button>
              <a class="btn tiny primary" data-act="dir" href="${googleDir(f.lat, f.lng)}" target="_blank" rel="noopener">${escapeHtml(t("map.openDir"))}</a>
            </div>
          </div>
          <span class="dist">${f.distance_m != null ? Math.round(f.distance_m) + " m" : ""}</span>
        </div>`).join("");

      state.mapLoaded = true;
    } catch (err) {
      mapNote(err.message || t("errGeneric"));
      list.innerHTML = `<div class="card"><p class="muted">${escapeHtml(err.message || t("errGeneric"))}</p></div>`;
    }
  }

  function openMapFor(category) {
    $("#map-category").value = category || "recyclable";
    state.mapLoaded = false;
    showTab("map");
  }

  // ---------------------------------------------------------------- history
  async function ensureTaxonomy() {
    if (state.taxonomy) return state.taxonomy;
    try { state.taxonomy = await api("/taxonomy", {}, 15000); }
    catch { state.taxonomy = []; }
    return state.taxonomy;
  }

  function itemName(id) {
    if (!state.taxonomy) return id.replaceAll("_", " ");
    for (const c of state.taxonomy) {
      const hit = (c.items || []).find((i) => i.id === id);
      if (hit) return hit[state.lang] || hit.en || id;
    }
    return id.replaceAll("_", " ");
  }

  async function loadHistory(silent = false) {
    if (!silent) $("#history-list").innerHTML = `<p class="muted small">${escapeHtml(t("loading"))}</p>`;
    try {
      const q = new URLSearchParams({ device_id: state.deviceId, limit: "100" });
      const r = await api("/history?" + q.toString(), {}, 15000);
      await ensureTaxonomy();
      $("#stat-scans").textContent = r.total ?? 0;
      $("#stat-points").textContent = r.eco_points ?? 0;
      $("#stat-categories").textContent = Object.keys(r.by_category || {}).length;
      const subtitle = $("#history-subtitle");
      if (subtitle) subtitle.textContent = t(r.image_storage ? "history.subtitleImages" : "history.subtitle");

      const max = Math.max(1, ...Object.values(r.by_category || {}));
      $("#cat-breakdown").innerHTML = Object.entries(r.by_category || {})
        .sort((a, b) => b[1] - a[1])
        .map(([cat, n]) => `
          <div class="bar">
            <span>${escapeHtml(t("cat_" + cat))}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${Math.round((n / max) * 100)}%"></div></div>
            <span>${n}</span>
          </div>`).join("");

      if (!r.scans?.length) {
        $("#history-list").innerHTML = `<div class="card"><p class="muted">${escapeHtml(t("historyEmpty"))}</p></div>`;
      } else {
        $("#history-list").innerHTML = r.scans.map((s) => {
          const d = new Date(s.created_at);
          const when = isNaN(d) ? s.created_at : d.toLocaleString(state.lang === "en" ? undefined : state.lang);
          const thumb = s.image_url
            ? `<img class="scan-thumb" src="${escapeHtml(s.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
            : `<span class="scan-thumb placeholder" aria-hidden="true">${CAT_EMOJI[s.category] || "♻️"}</span>`;
          return `
            <div class="scan-row">
              ${thumb}
              <div class="scan-meta">
                <strong>${escapeHtml(itemName(s.item))}</strong>
                <small>${escapeHtml(t("cat_" + s.category))}${s.uncertain ? " · ?" : ""} · ${escapeHtml(when)}</small>
              </div>
              <span class="points">+${s.eco_points}</span>
            </div>`;
        }).join("");
      }
      state.historyLoaded = true;
    } catch (err) {
      if (!silent) {
        $("#history-list").innerHTML = `<div class="card"><p class="muted">${escapeHtml(err.message || t("errGeneric"))}</p></div>`;
      }
    }
  }

  // ---------------------------------------------------------------- wiring
  function bind() {
    $$(".lang").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
    $$(".navbtn").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

    $("#camera").addEventListener("change", (e) => setFile(e.target.files[0]));
    $("#open-camera").addEventListener("click", openWebcam);
    $("#webcam-capture").addEventListener(
    "click",
    captureWebcamPhoto
    );
    $("#webcam-cancel").addEventListener(
    "click",
    stopWebcam
    );
    $("#upload").addEventListener("change", (e) => setFile(e.target.files[0]));
    $("#clear-photo").addEventListener("click", clearPhoto);
    $("#classify-btn").addEventListener("click", classify);
    $("#scan-go").addEventListener("click", classify);
    $("#extra-toggle").addEventListener("click", (e) => {
      const box = $("#scan-extra");
      const open = box.classList.toggle("hidden") === false;
      e.currentTarget.setAttribute("aria-expanded", String(open));
      if (open) {
        $("#barcode").focus();
        setTimeout(() => {
          const navTop = document.querySelector(".tabbar").getBoundingClientRect().top;
          const bottom = box.getBoundingClientRect().bottom;
          if (bottom > navTop - 10) {
            window.scrollBy(0, bottom - navTop + 18);
          }
        }, 90);
      }
    });

    $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat(); });
    $("#chat-input").addEventListener("input", (e) => autoGrow(e.target));
    $("#chat-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $("#chat-new").addEventListener("click", newChat);
    $$("#chips .chip").forEach((b, i) => b.addEventListener("click", () => {
      $("#chat-input").value = t("chat.q" + (i + 1));
      sendChat();
    }));
    $("#chat-photo").addEventListener("change", (e) => {
      const f = e.target.files[0];
      if (!f) return;
      if (f.size > 5 * 1024 * 1024) { toast(t("errLarge")); e.target.value = ""; return; }
      state.chatFile = f;
      $("#chat-attach-preview")?.remove();
      const url = URL.createObjectURL(f);
      const box = document.createElement("div");
      box.id = "chat-attach-preview";
      box.className = "attach-preview";
      box.innerHTML = `<img src="${url}" alt=""><span>${escapeHtml(t("attach"))}</span>
        <button type="button" class="icon-btn" style="width:28px;height:28px" aria-label="${escapeHtml(t("remove"))}">✕</button>`;
      box.querySelector("button").addEventListener("click", () => {
        state.chatFile = null;
        $("#chat-photo").value = "";
        box.remove();
      });
      $("#chat-form").before(box);
    });

    $("#locate-btn").addEventListener("click", () => { state.mapLoaded = false; locateAndLoad(); });
    $("#open-area").addEventListener("click", () => {
      const [lat, lng] = currentMapPoint();
      window.open(googleAreaUrl(lat, lng), "_blank", "noopener");
    });
    $("#map-category").addEventListener("change", () => {
      const [lat, lng] = currentMapPoint();
      setMapFrame(googleEmbedArea(lat, lng));
      loadFacilities(lat, lng);
    });
    $("#facility-list").addEventListener("click", (e) => {
      const card = e.target.closest(".facility");
      if (!card || card.dataset.idx == null) return;
      const f = (state.facilities || [])[Number(card.dataset.idx)];
      if (!f) return;
      $$(".facility").forEach((el) => el.classList.toggle("active", el === card));
      state.selectedFacility = f;
      if (e.target.closest("[data-act='dir']")) return;
      setMapFrame(googleEmbedRoute(f.lat, f.lng));
      document.querySelector(".map")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("#history-refresh").addEventListener("click", () => { state.historyLoaded = false; loadHistory(); });

    $("#account-btn").addEventListener("click", handleAuthClick);
    $("#auth-close").addEventListener("click", closeAuth);
    $("#auth-switch").addEventListener("click", toggleAuthMode);
    $("#auth-form").addEventListener("submit", submitAuth);

    window.addEventListener("hashchange", () => {
      const name = location.hash.replace("#", "");
      if (["scan", "chat", "map", "history"].includes(name)) showTab(name, { updateHash: false });
    });
  }

  let appBooted = false;

  // Keep basic navigation usable even if an unrelated widget fails during startup.
  // This fallback is active only until the normal listeners have been installed.
  document.addEventListener("click", (event) => {
    if (appBooted) return;
    const nav = event.target.closest && event.target.closest(".navbtn[data-tab]");
    if (nav) {
      event.preventDefault();
      showTab(nav.dataset.tab);
      return;
    }
    const lang = event.target.closest && event.target.closest(".lang[data-lang]");
    if (lang) {
      event.preventDefault();
      setLang(lang.dataset.lang);
    }
  }, true);

  window.addEventListener("error", (event) => {
    console.error("Kachra Mitra frontend error:", event.error || event.message);
    const box = $("#scan-error");
    if (box) {
      box.textContent = "The app encountered a browser error. Refresh the page; if it continues, open the browser console and share the error.";
      box.classList.remove("hidden");
    }
  });

  window.addEventListener("unhandledrejection", (event) => {
    console.error("Kachra Mitra async error:", event.reason);
  });

  function boot() {
    try {
      applyI18n();
      bind();
      appBooted = true;
      renderGreeting();
      restoreAuth();
      wakeServer();
      setInterval(() => {
        if (document.visibilityState === "visible") wakeServer();
      }, 10 * 60 * 1000);
      const start = location.hash.replace("#", "");
      showTab(["scan", "chat", "map", "history"].includes(start) ? start : "scan", { updateHash: false });
    } catch (error) {
      console.error("Kachra Mitra failed to initialize:", error);
      const box = $("#scan-error");
      if (box) {
        box.textContent = "The app could not initialize correctly. Refresh the page; if the problem continues, share the browser console error.";
        box.classList.remove("hidden");
      }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
