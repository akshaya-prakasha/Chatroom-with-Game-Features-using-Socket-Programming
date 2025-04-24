Secure Chat Application with Tic-Tac-Toe 

Contributors :-
 1) Akshaya Prakasha (PES1UG23CS052)
 2) Akshaj L Shastry (PES1UG23CS047) 

Summary :-
A Python-based secure chat application with a built-in Tic-Tac-Toe game, utilizing SSL/TLS for encrypted communication. With a PyQt5-based graphical user interface , users can register, log in, send messages, share files, request for direct messages and group chats, and play Tic-Tac-Toe with other users. 

Features: 
1) Secure Communication: Uses SSL/TLS for encrypted client-server communication. No communication is over raw TCP 

2) User Authentication: Supports user registration and login with password hashing. 

3) Chat Functionality:
   
     a)Public chat for all users.
    
     b)Direct messages (DMs) and group chats via invitations. 

5) File Sharing: Send and receive files securely. 

6) Tic-Tac-Toe Game: Play Tic-Tac-Toe with other users in real-time. 

7) GUI: Intuitive PyQt5-based interface with tabs for chats and a file explorer for received files. 

8) User Management: Displays active users and supports logout functionality. 

9) Multiple Clients and Servers: - Accepts multiple clients using threading, Clients are dynamically tracked and listed  

10) Protocol Development: - login handshake, user tracking, message broadcasting, file metadata transfer before file data 

11) Raw Sockets Handling: - Uses only Python's built-in socket module, handles disconnections and removes dead clients from the list

To Make sure SSL is implemented :-

 1) Run "openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes" in your terminal . Make sure its run in the same directory in which server.py and gui_client.py are present 
 2) This Generates a self-signed certificate and private key
 3) Once the command above is run on your terminal , you will get 2 files , they are cert.pem and key.pem
    
System Requirements :-
 1) Want to implement inside Mininet :- Linux System
 2) Want to implement outside Mininet :- Windows System

Run Instructions (Linux System):- 
1) Create a topology by running :- sudo mn --topo=linear,4 --mac
2) Inside the prompt, type xterm h1 and run python3 server.py
3) Again type xterm h2 and run python3 gui_client.py
4) For successive clients follow same procedure based on number of nodes created

Run Instructions (Windows System):- 
 1) python server.py
 2) Open another command prompt and run python gui_client.py , For successive Clients the same proceudre has to be followed 
