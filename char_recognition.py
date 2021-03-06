import cnn
import h5py
import json
import math
import numpy as np
import os
import stn
import sys
import tensorflow as tf
import time
import utils
from utils import logger


class Config():
  def __init__(self):
    with open('config.json', 'r') as json_file:
      json_data = json.load(json_file)

      self.dataset_dir_iiit5k = json_data['dataset_dir_iiit5k']
      self.dataset_dir_vgg = json_data['dataset_dir_vgg']
      self.use_iiit5k = json_data['use_iiit5k']

      self.height = json_data['height']
      self.window_size = json_data['window_size']
      self.jittering_percent = json_data['jittering_percent']
      self.embed_size = json_data['embed_size']

      self.lr = json_data['lr']
      self.num_epochs = json_data['num_epochs']
      self.batch_size = json_data['batch_size']

      self.use_stn = json_data['use_stn']

      self.debug = json_data['debug']
      self.debug_size = json_data['debug_size']
      self.load_char_ckpt = json_data['load_char_ckpt']
      self.ckpt_dir = json_data['ckpt_dir']
      self.test_only = json_data['test_only']
      self.test_and_save_every_n_steps = json_data['test_and_save_every_n_steps']
      self.visualize = json_data['visualize']
      self.visualize_dir = json_data['visualize_dir']


class CHAR_Model():
  def __init__(self, config):
    self.config = config
    self.add_placeholders()
    self.logits = self.add_model()
    self.loss = self.add_loss_op(self.logits)
    self.train_op = self.add_training_op(self.loss)

  def add_placeholders(self):
    self.inputs_placeholder = tf.placeholder(tf.float32,
        shape=[None, self.config.height, self.config.window_size, 1])
    self.labels_placeholder = tf.placeholder(tf.int64)
    self.dropout_placeholder = tf.placeholder(tf.float32)

  def add_model(self):
    with tf.variable_scope('CHAR') as scope:
      if self.config.use_stn:
        self.x_trans, self.variables_STN, self.saver_STN = stn.STN( \
            self.inputs_placeholder, self.dropout_placeholder, \
            self.config.height, self.config.window_size)
        logits, self.variables_CNN, self.saver_CNN = cnn.CNN( \
            self.x_trans, self.dropout_placeholder, \
            self.config.height, self.config.window_size)
      else:
        logits, self.variables_CNN, self.saver_CNN = cnn.CNN( \
            self.inputs_placeholder, self.dropout_placeholder, \
            self.config.height, self.config.window_size)

      with tf.variable_scope('fc6') as scope:
        a_fc6 = tf.nn.relu(logits)
        a_fc6_drop = tf.nn.dropout(a_fc6, 1-self.dropout_placeholder*0.5)

      with tf.variable_scope('fc7') as scope:
        W_fc7 = tf.get_variable('Weight', [128, self.config.embed_size], initializer=tf.contrib.layers.xavier_initializer())
        b_fc7 = tf.get_variable('Bias', [self.config.embed_size], initializer=tf.constant_initializer(0))
        logits = tf.matmul(a_fc6_drop, W_fc7)+b_fc7

      self.variables_FC = [W_fc7, b_fc7]
      self.saver_FC = tf.train.Saver({'W_fc7': W_fc7, 'b_fc7': b_fc7})

    return logits

  def add_loss_op(self, logits):
    losses = tf.nn.sparse_softmax_cross_entropy_with_logits(logits,
        self.labels_placeholder)
    loss = tf.reduce_mean(losses)

    self.diff = tf.argmax(logits, 1)-self.labels_placeholder

    return loss

  def add_training_op(self, loss):
    if self.config.use_stn:
      train_op1 = tf.train.AdamOptimizer(0.1*self.config.lr).minimize(loss,
          var_list=self.variables_STN)
      train_op2 = tf.train.AdamOptimizer(self.config.lr).minimize(loss,
          var_list=self.variables_CNN)
      train_op3 = tf.train.AdamOptimizer(self.config.lr).minimize(loss,
          var_list=self.variables_FC)
      train_op = tf.group(train_op1, train_op2, train_op3)
    else:
      train_op1 = tf.train.AdamOptimizer(self.config.lr).minimize(loss,
          var_list=self.variables_CNN)
      train_op2 = tf.train.AdamOptimizer(self.config.lr).minimize(loss,
          var_list=self.variables_FC)
      train_op = tf.group(train_op1, train_op2)

    return train_op

def main():
  config = Config()
  model = CHAR_Model(config)
  init = tf.initialize_all_variables()

  if not os.path.exists(model.config.ckpt_dir):
    os.makedirs(model.config.ckpt_dir)

  config = tf.ConfigProto(allow_soft_placement=True)

  with tf.Session(config=config) as session:
    session.run(init)
    best_loss = float('inf')
    corresponding_accuracy = 0 # accuracy corresponding to the best loss
    best_accuracy = 0
    corresponding_loss = float('inf') # loss corresponding to the best accuracy

    # restore previous session
    if model.config.load_char_ckpt or model.config.test_only:
      if os.path.isfile(model.config.ckpt_dir+'model_best_accuracy_cnn.ckpt'):
        if model.config.use_stn:
          model.saver_STN.restore(session, model.config.ckpt_dir+'model_best_accuracy_stn.ckpt')
        model.saver_CNN.restore(session, model.config.ckpt_dir+'model_best_accuracy_cnn.ckpt')
        model.saver_FC.restore(session, model.config.ckpt_dir+'model_best_accuracy_fc.ckpt')
        logger.info('<-------------------->')
        logger.info('model restored')
      if os.path.isfile(model.config.ckpt_dir+'char_best_loss.npy'):
        best_loss = np.load(model.config.ckpt_dir+'char_best_loss.npy')
        logger.info('best loss: '+str(best_loss))
      if os.path.isfile(model.config.ckpt_dir+'char_corr_accuracy.npy'):
        corresponding_accuracy = np.load(model.config.ckpt_dir+\
            'char_corr_accuracy.npy')
        logger.info('corresponding accuracy: '+str(corresponding_accuracy))
      if os.path.isfile(model.config.ckpt_dir+'char_best_accuracy.npy'):
        best_accuracy = np.load(model.config.ckpt_dir+'char_best_accuracy.npy')
        logger.info('best accuracy: '+str(best_accuracy))
      if os.path.isfile(model.config.ckpt_dir+'char_corr_loss.npy'):
        corresponding_loss = np.load(model.config.ckpt_dir+'char_corr_loss.npy')
        logger.info('corresponding loss: '+str(corresponding_loss))
      logger.info('<-------------------->')

    iterator_train = utils.data_iterator_char( \
        model.config.dataset_dir_iiit5k, model.config.dataset_dir_vgg, model.config.use_iiit5k, \
        model.config.height, model.config.window_size, \
        model.config.num_epochs, model.config.batch_size, \
        model.config.embed_size, model.config.jittering_percent, True, \
        model.config.visualize, model.config.visualize_dir)

    losses_train = []
    accuracies_train = []
    cur_epoch = 0
    step_epoch = 0

    # each step corresponds to one batch
    for step_train, (inputs_train, labels_train, epoch_train) in \
        enumerate(iterator_train):

      # test & save model
      if step_train%model.config.test_and_save_every_n_steps == 0:
        losses_test = []
        accuracies_test = []
        iterator_test = utils.data_iterator_char( \
            model.config.dataset_dir_iiit5k, model.config.dataset_dir_vgg, model.config.use_iiit5k, \
            model.config.height, model.config.window_size, \
            1, model.config.batch_size, \
            model.config.embed_size, model.config.jittering_percent, False, \
            model.config.visualize, model.config.visualize_dir)

        for step_test, (inputs_test, labels_test, epoch_test) in \
            enumerate(iterator_test):

          feed_test = {model.inputs_placeholder: inputs_test,
                       model.labels_placeholder: labels_test,
                       model.dropout_placeholder: 0}

          ret_test = session.run([model.loss, model.diff], feed_dict=feed_test)
          losses_test.append(ret_test[0])
          accuracies_test.append(float(np.sum(ret_test[1] == 0))/\
              ret_test[1].shape[0])

          # visualize the STN results
        #   if model.config.visualize and step_test < 10:
        #     utils.save_imgs(inputs_test, model.config.visualize_dir,
        #         'original'+str(step_test)+'-')
        #     utils.save_imgs(ret_test[2], model.config.visualize_dir,
        #         'trans'+str(step_test)+'-')

        cur_loss = np.mean(losses_test)
        cur_accuracy = np.mean(accuracies_test)

        if model.config.test_only:
          return

        # save three models: current model, model with the lowest loss, model
        # with the highest accuracy
        if cur_loss >= best_loss and cur_accuracy <= best_accuracy:
          if model.config.use_stn:
            model.saver_STN.save(session, model.config.ckpt_dir+'model_stn.ckpt')
          model.saver_CNN.save(session, model.config.ckpt_dir+'model_cnn.ckpt')
          model.saver_FC.save(session, model.config.ckpt_dir+'model_fc.ckpt')
          logger.info('cnn model saved')
        if cur_loss < best_loss:
          best_loss = cur_loss
          corresponding_accuracy = cur_accuracy
          if model.config.use_stn:
            model.saver_STN.save(session, model.config.ckpt_dir+'model_best_loss_stn.ckpt')
          model.saver_CNN.save(session, model.config.ckpt_dir+'model_best_loss_cnn.ckpt')
          model.saver_FC.save(session, model.config.ckpt_dir+'model_best_loss_fc.ckpt')
          logger.info('best loss model saved')
          np.save(model.config.ckpt_dir+'char_best_loss.npy', np.array(best_loss))
          np.save(model.config.ckpt_dir+'char_corr_accuracy.npy', np.array(corresponding_accuracy))
        if cur_accuracy > best_accuracy:
          best_accuracy = cur_accuracy
          corresponding_loss = cur_loss
          if model.config.use_stn:
            model.saver_STN.save(session, model.config.ckpt_dir+'model_best_accuracy_stn.ckpt')
          model.saver_CNN.save(session, model.config.ckpt_dir+'model_best_accuracy_cnn.ckpt')
          model.saver_FC.save(session, model.config.ckpt_dir+'model_best_accuracy_fc.ckpt')
          logger.info('best accuracy model saved')
          np.save(model.config.ckpt_dir+'char_best_accuracy.npy', np.array(best_accuracy))
          np.save(model.config.ckpt_dir+'char_corr_loss.npy', np.array(corresponding_loss))

        logger.info('<-------------------->')
        logger.info('test loss: %f (#batches = %d)',
            cur_loss, len(losses_test))
        logger.info('test accuracy: %f (#batches = %d)',
            cur_accuracy, len(accuracies_test))
        logger.info('best test loss: %f, corresponding accuracy: %f',
            best_loss, corresponding_accuracy)
        logger.info('best test accuracy: %f, corresponding loss: %f',
            best_accuracy, corresponding_loss)
        logger.info('<-------------------->')

      # new epoch, calculate average training loss and accuracy from last epoch
      if epoch_train != cur_epoch:
        logger.info('training loss in epoch %d, step %d: %f', cur_epoch, step_train,
            np.mean(losses_train[step_epoch:]))
        logger.info('training accuracy in epoch %d, step %d: %f', cur_epoch, step_train,
            np.mean(accuracies_train[step_epoch:]))
        step_epoch = step_train
        cur_epoch = epoch_train

      # train
      feed_train = {model.inputs_placeholder: inputs_train,
                    model.labels_placeholder: labels_train,
                    model.dropout_placeholder: 1}

      ret_train = session.run([model.train_op, model.loss, model.diff],
          feed_dict=feed_train)
      losses_train.append(ret_train[1])
      accuracies_train.append(float(np.sum(ret_train[2] == 0))/\
          ret_train[2].shape[0])
      logger.info('epoch %d, step %d: training loss = %f', epoch_train, step_train,
        ret_train[1])

if __name__ == '__main__':
  main()
