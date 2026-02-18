function startRecognition() {
    const recognition = new webkitSpeechRecognition();
    recognition.lang = "en-US";

    recognition.onresult = function(event) {
        document.getElementById("answer").value =
            event.results[0][0].transcript;
    };

    recognition.start();
}
