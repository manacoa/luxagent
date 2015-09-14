import rospy 
import json

from rostopic import get_topic_type

from ros_communication.rosbridge import ros_loader
from ros_communication.rosbridge import message_conversion
from ros_communication.rosbridge.topics import TopicNotEstablishedException, TypeConflictException

from rospy import Publisher
from rosbridge_library.internal import ros_loader, message_conversion

MAX_SIZE_PUBLICATION_BUFFER = 10
MAX_SIZE_ROS_PUBLICATION_QUEUE = 100

class RosPubSubApi(object):

	def open(self, ros_comm):
		self.ros_comm = ros_comm
		self.subscriptions = {}
		self.publication_channels = {}
		self.topic_types_identified = {}
		rospy.init_node('luxagent', anonymous=False)

	def subscribe_to_topics(self, ros_graph):
		for item in ros_graph:
			if (is_a_topic(item)):
				self.subscribe(topic_name(item))

	def unsubscribe_from_topics(self, ros_graph):
		for item in ros_graph:
			if (is_a_topic(item)):
				self.unsubscribe(topic_name(item))

	def publish_topic_message(self, topic, topicMessage):
		# Remove leading space from topic name
		topicKey = topic[1:]
		if topicKey in self.publication_channels:
			self.publication_channels[topicKey].publish(topicMessage)
		else:
			raise NameError("Tried to publish to unsbscribed topic: " + topicKey)	

	def msg_type_for_topic(self, topic):
		return self.subscriptions[topic].msg_type if (topic in self.subscriptions) else None

	# Polling topics for data			

	def schedule_topic_examinations(self, ros_graph):
		for item in ros_graph:
			if (is_a_topic(item)):
				self.schedule_find_topic_data(item)				

	def schedule_find_topic_data(self, item):
		topic = topic_name(item)
		if not topic in self.topic_types_identified:
			self.topic_types_identified[topic] = False

	def update_loop_actions(self, ros_graph):
		ros_graph = self.do_topic_examinations(ros_graph)
		return ros_graph

	def do_topic_examinations(self, ros_graph):
		for key in self.topic_types_identified:	
			if not self.topic_types_identified[key]:
				topic_type = get_topic_type(key)[0]
				if topic_type != None:
					self.topic_types_identified[key] = True
					index = self.index_of_topic_in_graph(key, ros_graph)
					if index > -1:
						ros_graph[index][1]['type'] = topic_type
						print "Added type %s to topic %s" % (topic_type, key)
					else:
						print "ERROR: Couldn't find %s in ros_graph" % key
						print ros_graph
						print "----------------"
				else:
					print "No reply on message type for topic %s" % key	
		return ros_graph			

	def index_of_topic_in_graph(self, key, ros_graph):
		for i in range(0, len(ros_graph)):
			if ros_graph[i][0] == 't  ' + key:
				return i
		return -1		

	# End of topic polling

	def subscribe(self, topic, msg_type=None):
		print
		print "*********************"
		print "Subscribing to %s" % topic			
		print

		# Subscribe to topic
		self.subscriptions[topic] = TopicSubscription(self.ros_comm, topic)
		self.subscriptions[topic].open()
		self.publication_channels[topic] = TopicPublicationChannel(self.ros_comm, topic)
		self.publication_channels[topic].open()

	def unsubscribe(self, topic):
		print "unsubscribing from %s" % topic	
		print		
		self.subscription[topic].close()

class TopicPublicationChannel(object):		

	def __init__(self, ros_comm, topic):
		self.ros_comm = ros_comm
		# save topic name with leading space
		self.topic = topic
		self.buffer = []
		self.publisher = False
		self.msg_type = None

	def open(self):
		foo = 0

	def publish(self, message):
		self.publish_to_buffer(message)
		if (self.ready_to_publish_to_graph()):
			self.flush_buffer()

	def publish_to_buffer(self, message):
		self.buffer.append(message)	
		if (len(self.buffer)>MAX_SIZE_PUBLICATION_BUFFER):
			raise NameError("Publication buffer full for " + self.topic)

	def flush_buffer(self):
		for buffered_message in self.buffer:
			self.publish_to_graph(buffered_message)
			self.buffer.pop(0)

	def ready_to_publish_to_graph(self):
		# Return true if subscription has successfully found out message type
		# TODO: Could also implement RosBridge's scheme of waiting for all subscriptions to be ready
		if (self.msg_type == None):
			self.msg_type = self.ros_comm.ros_pubsub_api.msg_type_for_topic(self.topic)
		return (self.msg_type != None)

	def publish_to_graph(self, message):
		topicKey = self.topic[1:]
		if (not self.publisher):
			msg_class = ros_loader.get_message_class(self.msg_type)
			self.publisher = Publisher(topicKey, msg_class, latch=False, queue_size=MAX_SIZE_ROS_PUBLICATION_QUEUE)				
		message_instance = self.json_message_to_message_instance(message)
		self.publisher.publish(message_instance)	

	def json_message_to_message_instance(self, message):
		msg_class = ros_loader.get_message_class(self.msg_type)
		instance = msg_class()
		message_conversion.populate_instance(message, instance)
		return instance

class TopicSubscription(object):

	def __init__(self, ros_comm, topic, msg_type=None):
		self.ros_comm = ros_comm
		self.topic = topic
		self.msg_type = msg_type
		self.message_count = 0

	def open(self):	
		# First check to see if the topic is already established
		topic_type = get_topic_type(self.topic)[0]

		# If it's not established and no type was specified, exception
		if self.msg_type is None and topic_type is None:
			raise TopicNotEstablishedException(self.topic)

		# Use the established topic type if none was specified
		if self.msg_type is None:
			self.msg_type = topic_type

		# Load the message class, propagating any exceptions from bad msg types
		self.msg_class = ros_loader.get_message_class(self.msg_type)

		# Make sure the specified msg type and established msg type are same
		if topic_type is not None and topic_type != self.msg_class._type:
			raise TypeConflictException(self.topic, topic_type, self.msg_class._type)

		# Subscribe to topic
		self.subscription = rospy.Subscriber(self.topic, self.msg_class, self.receive_message)

	def close(self):
		self.subscription.unregister()

	def receive_message(self, msg, callbacks=None):
		# Try to convert the msg to JSON
		message_json = None
		try:
			message_json = message_conversion.extract_values(msg)
		except Exception as exc:
			rospy.logerr("Exception while converting messages in subscriber callback : %s", exc)
			return
		#print 
		#print message_json
		#print
		message_hash = json.loads(json.dumps(message_json))		
		#self.ros_comm.event_message_from_topic(self.topic, self.msg_type, self.message_count, message_hash)	
		self.ros_comm.event_message_from_topic(' ' + self.topic, self.msg_type, self.message_count, message_hash)	
		self.message_count = self.message_count + 1
		#print "Topic %s received message %s" % (self.topic, self.message_count)
		#print "Topic '%s' received message" % self.topic
	

def is_a_topic(item):
	key = item[0]
	return (key[0]=='t')

def topic_name(item):
	key = item[0]
	return key[3:]

