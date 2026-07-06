//jscript functions for tippgame version

 
// closes a navbar
function w3_open(value) {
    document.getElementById("mySidebar").style.width = value;
    document.getElementById("mySidebar").style.display = "block";
    document.getElementsByClassName("w3-overlay")[0].style.display = "block";   
}

// opens the navbar
function w3_close() {
    document.getElementById("mySidebar").style.display = "none";
    document.getElementsByClassName("w3-overlay")[0].style.display = "none";    
}

function AccFunc(name) {
    var x = document.getElementById(name);
    if (x.className.indexOf("w3-show") == -1) {
        x.className += " w3-show";
        // x.previousElementSibling.className += " ehc-blue-2";
    } else { 
        x.className = x.className.replace(" w3-show", "");
        x.previousElementSibling.className = 
        x.previousElementSibling.className.replace(" w3-green", "");
    }
}

function togglearea(ele) {
  // alert(ele.id); //
  var x = document.getElementById(ele.id);
  if (x.className.indexOf("w3-show") == -1) {
    x.className += " w3-show";
  } else {
    x.className = x.className.replace(" w3-show", "");
  }
}

// what to do after document load
$(document).ready(function(){
    
    var url = window.location.pathname; 
    
    $("#nav_link").on("click",function(){w3_close();});
    $("#o_sidebar").on("click",function() {w3_open('20%');});    
    $("#o_msidebar").on("click",function() {w3_open('60%');});     
    
    $("#settingsAccButton").on("click",function() {AccFunc('settingsAcc');});   
    $("#dcesbAccButton").on("click",function() {AccFunc('dcesbAcc');});
    $("#goalAccButton").on("click",function() {AccFunc('goalAcc');});    
    $("#pnltyAccButton").on("click",function() {AccFunc('pnltyAcc');});   
    $("#tstatAccButton").on("click",function() {AccFunc('tstatAcc');});    
    // $("#refstatAccButton").on("click",function() {AccFunc('refstatAcc');});  
    $("#matchAccButton").on("click",function() {AccFunc('matchAcc');}); 	
    $("#tgameAccButton").on("click",function() {AccFunc('tgameAcc');});
});
