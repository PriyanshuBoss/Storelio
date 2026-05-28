
function delete_object(id) {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", '/admin/product/product/custom_image_delete/');
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.setRequestHeader("X-CSRFToken", getCookie("csrftoken"));
    xhr.onload = function() {
      if (xhr.status === 200) {
        // Success - reload the page to show the updated list of objects
        window.location.reload();
      } else {
        // Error - display an error message
        alert("There was an error deleting the object.");
      }
    };
    var data = JSON.stringify({ 'image_id': id });
    xhr.send(data);
  }
  
  // Helper function to get the value of a CSRF cookie
  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      var cookies = document.cookie.split(";");
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
