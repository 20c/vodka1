import webapp
import uwsgi

application = webapp.get_application()
serverConf = application.config.get("server")

uwsgi.atexit = webapp.shutdown_handler
